#include <Arduino.h>
#include <ArduinoJson.h>
#include <ESP8266HTTPClient.h>
#include <ESP8266WiFi.h>
#include <WiFiClient.h>
#include <WiFiClientSecureBearSSL.h>
#include <Wire.h>
#include <LittleFS.h>
#include <SoftwareSerial.h>
#include <WiFiManager.h>
#include <Adafruit_BMP280.h>
#include <time.h>
#include "device_config.h"

namespace {
constexpr uint8_t RELAY_PIN = D5;
constexpr uint8_t CAMERA_UART_RX_PIN = D6;  // Recebe do GPIO14 da ESP32-CAM.
constexpr uint8_t CAMERA_UART_TX_PIN = D7;  // Envia ao GPIO13 da ESP32-CAM.
constexpr uint8_t WIFI_RESET_PIN = D0;       // Botao para GND, pressionar 5 s.
constexpr bool RELAY_ACTIVE_LOW = true;
constexpr char FIRMWARE_VERSION[] = "horta-esp8266-1.0.0";
constexpr uint32_t CAMERA_ACK_TIMEOUT_MS = 5000;
constexpr uint32_t WIFI_RESET_HOLD_MS = 5000;
Adafruit_BMP280 bmp;
SoftwareSerial cameraSerial(CAMERA_UART_RX_PIN, CAMERA_UART_TX_PIN);
bool bmpReady = false, relayOn = false;
uint32_t sequenceNumber = 0, lastTelemetryAt = 0, lastHeartbeatAt = 0;
uint32_t lastCommandPollAt = 0, lastWifiAttemptAt = 0;
uint32_t pumpStopAt = 0;
uint32_t lastConfigPollAt = 0;
String cachedConfiguration = "{}";
String lastIrrigationBucket;
uint32_t wifiResetPressedAt = 0;
bool wifiResetTriggered = false;

bool waitCameraAck(const char* expectedType, uint32_t timeoutMs) {
  String line;
  uint32_t startedAt = millis();
  while (millis() - startedAt < timeoutMs) {
    while (cameraSerial.available()) {
      char value = static_cast<char>(cameraSerial.read());
      if (value == '\n') {
        JsonDocument response;
        if (!deserializeJson(response, line) &&
            response["type"] == expectedType && response["status"] == "ok") return true;
        line = "";
      } else if (value != '\r' && line.length() < 384) line += value;
    }
    delay(10);
    yield();
  }
  return false;
}

void sendCameraMessage(JsonDocument& message) {
  serializeJson(message, cameraSerial);
  cameraSerial.write('\n');
  cameraSerial.flush();
}

void provisionCameraWifi() {
  String ssid = WiFi.SSID();
  String password = WiFi.psk();
  if (ssid.isEmpty()) {
    Serial.println(F("Camera provisioning skipped: Wi-Fi SSID unavailable"));
    return;
  }
  while (cameraSerial.available()) cameraSerial.read();
  JsonDocument message;
  message["type"] = "wifi_config";
  message["ssid"] = ssid;
  message["password"] = password;
  sendCameraMessage(message);
  Serial.printf("Camera provisioning sent for SSID: %s\n", ssid.c_str());
  Serial.println(waitCameraAck("wifi_ack", CAMERA_ACK_TIMEOUT_MS)
                     ? F("Camera Wi-Fi provisioned")
                     : F("Camera provisioning timeout; controller continues normally"));
}

void resetAllWifi() {
  JsonDocument message;
  message["type"] = "wifi_reset";
  sendCameraMessage(message);
  Serial.println(waitCameraAck("wifi_reset_ack", 2000)
                     ? F("Camera Wi-Fi reset confirmed")
                     : F("Camera Wi-Fi reset timeout"));
  WiFiManager manager;
  manager.resetSettings();
  Serial.println(F("Controller Wi-Fi erased; restarting in provisioning mode"));
  delay(300);
  ESP.restart();
}

void checkWifiResetButton() {
  if (digitalRead(WIFI_RESET_PIN) == LOW) {
    if (!wifiResetPressedAt) wifiResetPressedAt = millis();
    if (!wifiResetTriggered && millis() - wifiResetPressedAt >= WIFI_RESET_HOLD_MS) {
      wifiResetTriggered = true;
      resetAllWifi();
    }
  } else {
    wifiResetPressedAt = 0;
    wifiResetTriggered = false;
  }
}

void setRelay(bool on) {
  relayOn = on;
  digitalWrite(RELAY_PIN, (on == RELAY_ACTIVE_LOW) ? LOW : HIGH);
}

String utcNow() {
  time_t now = time(nullptr);
  if (now < 1700000000) return "";
  struct tm value;
  gmtime_r(&now, &value);
  char buffer[25];
  strftime(buffer, sizeof(buffer), "%Y-%m-%dT%H:%M:%SZ", &value);
  return String(buffer);
}

String nextKey(const char* channel) {
  return String(ESP.getChipId(), HEX) + "-" + channel + "-" +
         String(static_cast<uint32_t>(time(nullptr))) + "-" + String(sequenceNumber++);
}

bool beginHttp(HTTPClient& http, WiFiClient& plain,
               BearSSL::WiFiClientSecure& secure, const String& path) {
  String url = String(API_BASE_URL) + "/api/v1/device/" + path;
  if (url.startsWith("https://")) {
    if (strlen(HTTPS_ROOT_CA) < 40) {
      Serial.println(F("HTTPS_ROOT_CA ausente; HTTPS cancelado"));
      return false;
    }
    static BearSSL::X509List trustAnchor(HTTPS_ROOT_CA);
    secure.setTrustAnchors(&trustAnchor);
    if (!http.begin(secure, url)) return false;
  } else if (!http.begin(plain, url)) return false;
  http.setTimeout(10000);
  http.addHeader("Authorization", String("Device ") + DEVICE_API_TOKEN);
  http.addHeader("Content-Type", "application/json");
  return true;
}

int apiRequest(const char* method, const String& path, const String& body, String& response) {
  if (WiFi.status() != WL_CONNECTED) return -1;
  HTTPClient http;
  WiFiClient plain;
  BearSSL::WiFiClientSecure secure;
  if (!beginHttp(http, plain, secure, path)) return -2;
  int status = strcmp(method, "GET") == 0 ? http.GET() : http.POST(body);
  if (status > 0) response = http.getString();
  http.end();
  return status;
}

void sendTelemetry() {
  String recordedAt = utcNow();
  if (!bmpReady || recordedAt.isEmpty()) return;
  float temperature = bmp.readTemperature(), pressure = bmp.readPressure() / 100.0F;
  if (!isfinite(temperature) || !isfinite(pressure)) return;
  JsonDocument doc;
  JsonArray readings = doc["readings"].to<JsonArray>();
  JsonObject item = readings.add<JsonObject>();
  item["channel"] = "air-temperature";
  item["value"] = temperature;
  item["recorded_at"] = recordedAt;
  item["idempotency_key"] = nextKey("temperature");
  item = readings.add<JsonObject>();
  item["channel"] = "air-pressure";
  item["value"] = pressure;
  item["recorded_at"] = recordedAt;
  item["idempotency_key"] = nextKey("pressure");
  String body, response;
  serializeJson(doc, body);
  int status = apiRequest("POST", "telemetry/", body, response);
  Serial.printf("telemetry: HTTP %d %s\n", status, response.c_str());
}

void sendHeartbeat() {
  String recordedAt = utcNow();
  if (recordedAt.isEmpty()) return;
  JsonDocument doc;
  doc["recorded_at"] = recordedAt;
  doc["uptime_seconds"] = millis() / 1000UL;
  doc["signal_strength"] = WiFi.RSSI();
  doc["free_heap_bytes"] = ESP.getFreeHeap();
  doc["firmware_version"] = FIRMWARE_VERSION;
  doc["diagnostics"]["bmp280"] = bmpReady;
  doc["diagnostics"]["relay_on"] = relayOn;
  String body, response;
  serializeJson(doc, body);
  Serial.printf("heartbeat: HTTP %d\n", apiRequest("POST", "heartbeat/", body, response));
}

void acknowledge(const String& id, bool succeeded, const String& detail) {
  JsonDocument doc;
  doc["status"] = succeeded ? "succeeded" : "failed";
  doc["result"]["relay"] = relayOn;
  doc["result"]["detail"] = detail;
  String body, response;
  serializeJson(doc, body);
  Serial.printf("ack: HTTP %d\n", apiRequest("POST", "commands/" + id + "/ack/", body, response));
}

void pollCommands() {
  String response;
  int status = apiRequest("GET", "commands/", "", response);
  if (status != HTTP_CODE_OK) {
    Serial.printf("commands: HTTP %d\n", status);
    return;
  }
  JsonDocument doc;
  if (deserializeJson(doc, response)) return;
  for (JsonObject command : doc["commands"].as<JsonArray>()) {
    String id = command["id"] | "", channel = command["channel"] | "";
    String type = command["type"] | "";
    if (channel == "pump" && type == "set_state" && command["payload"]["on"].is<bool>()) {
      bool on = command["payload"]["on"].as<bool>();
      setRelay(on);
      String mode = command["payload"]["mode"] | "";
      pumpStopAt = on && mode == "safe_preset" ? millis() + SAFE_PUMP_DURATION_MS : 0;
      acknowledge(id, true, "relay atualizado");
    } else acknowledge(id, false, "canal ou comando nao suportado");
  }
}

void connectWifi() {
  if (WiFi.status() == WL_CONNECTED ||
      (lastWifiAttemptAt && millis() - lastWifiAttemptAt < 10000UL)) return;
  lastWifiAttemptAt = millis();
  WiFi.mode(WIFI_STA);
  WiFi.reconnect();
}

void saveConfiguration(const String& value) {
  File file = LittleFS.open("/device_config.json", "w");
  if (!file) return;
  file.print(value);
  file.close();
  cachedConfiguration = value;
}

void loadConfiguration() {
  if (!LittleFS.begin()) return;
  File file = LittleFS.open("/device_config.json", "r");
  if (file) {
    cachedConfiguration = file.readString();
    file.close();
  }
}

void fetchConfiguration() {
  HTTPClient http;
  WiFiClient plain;
  BearSSL::WiFiClientSecure secure;
  String url = String(API_BASE_URL) + "/api/device/config/";
  bool started = false;
  if (url.startsWith("https://")) {
    if (strlen(HTTPS_ROOT_CA) < 40) return;
    static BearSSL::X509List trustAnchor(HTTPS_ROOT_CA);
    secure.setTrustAnchors(&trustAnchor);
    started = http.begin(secure, url);
  } else started = http.begin(plain, url);
  if (!started) return;
  http.addHeader("Authorization", String("Device ") + DEVICE_API_TOKEN);
  http.addHeader("X-Device-ID", DEVICE_ID);
  int status = http.GET();
  if (status == HTTP_CODE_OK) saveConfiguration(http.getString());
  Serial.printf("config: HTTP %d\n", status);
  http.end();
}

void runOfflineAutomation() {
  if (pumpStopAt || cachedConfiguration.length() < 3) return;
  time_t now = time(nullptr);
  if (now < 1700000000) return;
  struct tm local;
  localtime_r(&now, &local);
  char current[6], bucket[18];
  strftime(current, sizeof(current), "%H:%M", &local);
  strftime(bucket, sizeof(bucket), "%Y%m%d-%H:%M", &local);
  JsonDocument doc;
  if (deserializeJson(doc, cachedConfiguration)) return;
  JsonObject irrigation = doc["irrigation"];
  if (!(irrigation["enabled"] | false)) return;
  for (JsonVariant value : irrigation["times"].as<JsonArray>()) {
    if (value.as<String>() == current && lastIrrigationBucket != bucket) {
      uint32_t duration = irrigation["duration_seconds"] | (SAFE_PUMP_DURATION_MS / 1000UL);
      duration = constrain(duration, 1UL, 300UL);
      setRelay(true);
      pumpStopAt = millis() + duration * 1000UL;
      lastIrrigationBucket = bucket;
      Serial.println(F("irrigacao iniciada pela configuracao local"));
      break;
    }
  }
}
}

void setup() {
  Serial.begin(115200);
  cameraSerial.begin(9600);
  pinMode(WIFI_RESET_PIN, INPUT_PULLUP);
  pinMode(RELAY_PIN, OUTPUT);
  setRelay(false);
  Wire.begin(D2, D1);
  bmpReady = bmp.begin(0x76) || bmp.begin(0x77);
  Serial.printf("\nBMP280: %s\n", bmpReady ? "ok" : "nao encontrado");
  loadConfiguration();
  WiFiManager manager;
  manager.setConfigPortalTimeout(180);
  String accessPoint = String("Horta-") + String(ESP.getChipId(), HEX);
  if (!manager.autoConnect(accessPoint.c_str())) {
    Serial.println(F("Provisionamento expirou; reiniciando"));
    ESP.restart();
  }
  Serial.printf("Wi-Fi conectado: %s\n", WiFi.localIP().toString().c_str());
  provisionCameraWifi();
  // MVP em America/Sao_Paulo (UTC-3, atualmente sem horario de verao).
  configTime(-3 * 3600, 0, "pool.ntp.org", "time.google.com");
}

void loop() {
  checkWifiResetButton();
  connectWifi();
  if (pumpStopAt && static_cast<int32_t>(millis() - pumpStopAt) >= 0) {
    setRelay(false);
    pumpStopAt = 0;
    Serial.println(F("bomba desligada pelo temporizador de seguranca"));
  }
  runOfflineAutomation();
  if (WiFi.status() != WL_CONNECTED) { delay(50); return; }
  uint32_t now = millis();
  if (!lastTelemetryAt || now - lastTelemetryAt >= TELEMETRY_INTERVAL_MS) {
    lastTelemetryAt = now; sendTelemetry();
  }
  if (!lastHeartbeatAt || now - lastHeartbeatAt >= HEARTBEAT_INTERVAL_MS) {
    lastHeartbeatAt = now; sendHeartbeat();
  }
  if (!lastCommandPollAt || now - lastCommandPollAt >= COMMAND_POLL_INTERVAL_MS) {
    lastCommandPollAt = now; pollCommands();
  }
  if (!lastConfigPollAt || now - lastConfigPollAt >= CONFIG_POLL_INTERVAL_MS) {
    lastConfigPollAt = now; fetchConfiguration();
  }
  delay(20);
}

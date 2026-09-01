#include <Arduino.h>
#include <ArduinoJson.h>
#include <ESP8266HTTPClient.h>
#include <ESP8266WiFi.h>
#include <WiFiClient.h>
#include <WiFiClientSecureBearSSL.h>
#include <Wire.h>
#include <Adafruit_BMP280.h>
#include <time.h>
#include "device_config.h"

namespace {
constexpr uint8_t RELAY_PIN = D5;
constexpr bool RELAY_ACTIVE_LOW = true;
constexpr char FIRMWARE_VERSION[] = "horta-esp8266-1.0.0";
Adafruit_BMP280 bmp;
bool bmpReady = false, relayOn = false;
uint32_t sequenceNumber = 0, lastTelemetryAt = 0, lastHeartbeatAt = 0;
uint32_t lastCommandPollAt = 0, lastWifiAttemptAt = 0;
uint32_t pumpStopAt = 0;

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
  WiFi.begin(WIFI_SSID, WIFI_PASSWORD);
}
}

void setup() {
  Serial.begin(115200);
  pinMode(RELAY_PIN, OUTPUT);
  setRelay(false);
  Wire.begin(D2, D1);
  bmpReady = bmp.begin(0x76) || bmp.begin(0x77);
  Serial.printf("\nBMP280: %s\n", bmpReady ? "ok" : "nao encontrado");
  connectWifi();
  configTime(0, 0, "pool.ntp.org", "time.google.com");
}

void loop() {
  connectWifi();
  if (pumpStopAt && static_cast<int32_t>(millis() - pumpStopAt) >= 0) {
    setRelay(false);
    pumpStopAt = 0;
    Serial.println(F("bomba desligada pelo temporizador de seguranca"));
  }
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
  delay(20);
}

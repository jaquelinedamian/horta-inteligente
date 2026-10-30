#include <Arduino.h>
#include <ArduinoJson.h>
#include <ESP8266HTTPClient.h>
#include <ESP8266WiFi.h>
#include <WiFiClient.h>
#include <WiFiClientSecureBearSSL.h>
#include <Wire.h>
#include <LittleFS.h>
#include <WiFiManager.h>
#include <Adafruit_BMP280.h>
#include <time.h>

#include "device_config.h"

namespace {

// ============================================================
// PINOS
// ============================================================

constexpr uint8_t PUMP_RELAY_PIN = D5;
constexpr uint8_t LIGHT_RELAY_PIN = D6;
constexpr uint8_t SOIL_SENSOR_PIN = A0;

constexpr bool PUMP_RELAY_ACTIVE_LOW = true;
constexpr bool LIGHT_RELAY_ACTIVE_LOW = true;

constexpr char FIRMWARE_VERSION[] =
    "horta-esp8266-1.3.0";

// ============================================================
// SENSOR / ESTADO
// ============================================================

Adafruit_BMP280 bmp;

bool bmpReady = false;
bool pumpRelayOn = false;
bool lightRelayOn = false;
int soilRaw = 0;
float soilPercent = 0.0F;

uint32_t sequenceNumber = 0;

uint32_t lastTelemetryAt = 0;
uint32_t lastHeartbeatAt = 0;
uint32_t lastCommandPollAt = 0;
uint32_t lastWifiAttemptAt = 0;
uint32_t lastConfigPollAt = 0;

uint32_t pumpStopAt = 0;

String cachedConfiguration = "{}";
String lastIrrigationBucket;
String lastLightingBucket;

// ============================================================
// RESET DE WIFI
// ============================================================

void resetAllWifi() {

  Serial.println();
  Serial.println(
      F("Apagando Wi-Fi salvo do controlador...")
  );

  WiFiManager manager;

  manager.resetSettings();

  WiFi.disconnect(true);

  Serial.println(
      F("Wi-Fi apagado.")
  );

  Serial.println(
      F("Reiniciando em modo de configuracao...")
  );

  delay(500);

  ESP.restart();
}


// ============================================================
// RELE / BOMBA
// ============================================================

uint8_t relayLevel(bool on, bool activeLow) {
  return on == activeLow ? LOW : HIGH;
}

void setPumpState(bool on) {
  pumpRelayOn = on;
  digitalWrite(PUMP_RELAY_PIN, relayLevel(on, PUMP_RELAY_ACTIVE_LOW));
}

void setLightState(bool on) {
  lightRelayOn = on;
  digitalWrite(LIGHT_RELAY_PIN, relayLevel(on, LIGHT_RELAY_ACTIVE_LOW));
}

float calibratedSoilPercent(int raw) {
  int dryRaw = 850;
  int wetRaw = 350;
  JsonDocument config;
  if (!deserializeJson(config, cachedConfiguration)) {
    dryRaw = config["soil_moisture"]["dry_raw"] | dryRaw;
    wetRaw = config["soil_moisture"]["wet_raw"] | wetRaw;
  }
  if (dryRaw == wetRaw) return 0.0F;
  return constrain(100.0F * (raw - dryRaw) / (wetRaw - dryRaw), 0.0F, 100.0F);
}


// ============================================================
// DATA/HORA
// ============================================================

constexpr time_t MIN_VALID_EPOCH = 1700000000;

String utcNow();

bool isTimeSynchronized() {

  return time(nullptr) >= MIN_VALID_EPOCH;
}


bool waitForTimeSynchronization(
    uint32_t timeoutMs = 15000UL
) {

  Serial.println(F("Sincronizando horario..."));

  const uint32_t startedAt = millis();

  while (
      !isTimeSynchronized() &&
      millis() - startedAt < timeoutMs
  ) {

    delay(250);
    yield();
  }

  if (!isTimeSynchronized()) {

    Serial.println(
        F("Falha ao sincronizar horario dentro do timeout.")
    );

    return false;
  }

  Serial.print(F("Horario sincronizado: "));
  Serial.println(utcNow());

  return true;
}

String utcNow() {

  time_t now = time(nullptr);

  if (now < MIN_VALID_EPOCH) {

    return "";
  }

  struct tm value;

  gmtime_r(&now, &value);

  char buffer[25];

  strftime(
      buffer,
      sizeof(buffer),
      "%Y-%m-%dT%H:%M:%SZ",
      &value
  );

  return String(buffer);
}


// ============================================================
// ID DE TELEMETRIA
// ============================================================

String nextKey(const char* channel) {

  return String(ESP.getChipId(), HEX)
      + "-"
      + channel
      + "-"
      + String(
          static_cast<uint32_t>(
              time(nullptr)
          )
        )
      + "-"
      + String(sequenceNumber++);
}


// ============================================================
// HTTP / HTTPS
// ============================================================

void printHttpsDiagnostics() {

  Serial.println(F("API host: horta-inteligente.onrender.com"));
  Serial.printf("Wi-Fi status: %d (%s)\n",
      WiFi.status(),
      WiFi.status() == WL_CONNECTED ? "conectado" : "desconectado");
  Serial.print(F("IP local: "));
  Serial.println(WiFi.localIP());
  Serial.printf("RSSI: %d dBm\n", WiFi.RSSI());
  Serial.printf("Hora atual do ESP8266: %ld\n",
      static_cast<long>(time(nullptr)));
}


void printRequestError(
    const char* channel,
    HTTPClient& http,
    BearSSL::WiFiClientSecure& secure,
    int status
) {

  Serial.printf(
      "%s: HTTP %d - %s\n",
      channel,
      status,
      http.errorToString(status).c_str()
  );

  char sslMessage[160] = {0};
  const int sslError = secure.getLastSSLError(
      sslMessage,
      sizeof(sslMessage)
  );

  Serial.printf(
      "%s: TLS %d - %s\n",
      channel,
      sslError,
      sslMessage[0] ? sslMessage : "sem erro SSL registrado"
  );
}

bool beginHttp(
    HTTPClient& http,
    WiFiClient& plain,
    BearSSL::WiFiClientSecure& secure,
    const String& path
) {

  String url =
      String(API_BASE_URL)
      + "/api/v1/device/"
      + path;


  if (url.startsWith("https://")) {

    if (!isTimeSynchronized()) {

      Serial.println(
          F("HTTPS adiado: horario do ESP8266 ainda nao e valido")
      );

      return false;
    }

    printHttpsDiagnostics();

    if (strlen(HTTPS_ROOT_CA) < 40) {

      Serial.println(
          F("HTTPS_ROOT_CA ausente; HTTPS cancelado")
      );

      return false;
    }

    static BearSSL::X509List trustAnchor(
        HTTPS_ROOT_CA
    );

    secure.setTrustAnchors(
        &trustAnchor
    );

    if (!http.begin(secure, url)) {

      return false;
    }
  }

  else {

    if (!http.begin(plain, url)) {

      return false;
    }
  }


  http.setTimeout(10000);

  http.addHeader(
      "Authorization",
      String("Device ") + DEVICE_API_TOKEN
  );

  http.addHeader(
      "Content-Type",
      "application/json"
  );

  return true;
}


int apiRequest(
    const char* method,
    const char* channel,
    const String& path,
    const String& body,
    String& response
) {

  if (WiFi.status() != WL_CONNECTED) {

    return -1;
  }

  HTTPClient http;
  WiFiClient plain;
  BearSSL::WiFiClientSecure secure;

  if (!beginHttp(
          http,
          plain,
          secure,
          path
      )) {

    printRequestError(
        channel,
        http,
        secure,
        HTTPC_ERROR_SEND_HEADER_FAILED
    );

    return -2;
  }


  int status;

  if (strcmp(method, "GET") == 0) {

    status = http.GET();
  }

  else {

    status = http.POST(body);
  }


  if (status > 0) {

    response = http.getString();
  }

  else {

    printRequestError(
        channel,
        http,
        secure,
        status
    );
  }

  http.end();

  return status;
}


// ============================================================
// TELEMETRIA
// ============================================================

void sendTelemetry() {

  String recordedAt = utcNow();

  if (
      !bmpReady ||
      recordedAt.isEmpty()
  ) {

    return;
  }


  float temperature =
      bmp.readTemperature();

  float pressure =
      bmp.readPressure() / 100.0F;


  if (
      !isfinite(temperature) ||
      !isfinite(pressure)
  ) {

    return;
  }


  JsonDocument doc;

  JsonArray readings =
      doc["readings"].to<JsonArray>();


  JsonObject temperatureItem =
      readings.add<JsonObject>();

  temperatureItem["channel"] =
      "air-temperature";

  temperatureItem["value"] =
      temperature;

  temperatureItem["recorded_at"] =
      recordedAt;

  temperatureItem["idempotency_key"] =
      nextKey("temperature");


  JsonObject pressureItem =
      readings.add<JsonObject>();

  pressureItem["channel"] =
      "air-pressure";

  pressureItem["value"] =
      pressure;

  pressureItem["recorded_at"] =
      recordedAt;

  pressureItem["idempotency_key"] =
      nextKey("pressure");

  soilRaw = analogRead(SOIL_SENSOR_PIN);
  soilPercent = calibratedSoilPercent(soilRaw);

  JsonObject soilItem = readings.add<JsonObject>();
  soilItem["channel"] = "soil-moisture";
  soilItem["value"] = soilPercent;
  soilItem["recorded_at"] = recordedAt;
  soilItem["idempotency_key"] = nextKey("soil");
  soilItem["raw"]["raw"] = soilRaw;


  String body;
  String response;

  serializeJson(
      doc,
      body
  );


  int status =
      apiRequest(
          "POST",
          "telemetry",
          "telemetry/",
          body,
          response
      );


  if (status >= 0) {

    Serial.printf(
        "telemetry: HTTP %d\n",
        status
    );

    if (status == HTTP_CODE_BAD_REQUEST) {

      JsonDocument errorDocument;
      DeserializationError error =
          deserializeJson(errorDocument, response);

      if (!error && errorDocument["detail"].is<const char*>()) {

        Serial.print(F("telemetry: detail: "));
        Serial.println(
            errorDocument["detail"].as<const char*>()
        );
      }

      else {

        Serial.print(F("telemetry: resposta: "));
        Serial.println(response);
      }
    }
  }
}


// ============================================================
// HEARTBEAT
// ============================================================

void sendHeartbeat() {

  String recordedAt = utcNow();

  if (recordedAt.isEmpty()) {

    return;
  }


  JsonDocument doc;

  doc["recorded_at"] =
      recordedAt;

  doc["uptime_seconds"] =
      millis() / 1000UL;

  doc["signal_strength"] =
      WiFi.RSSI();

  doc["free_heap_bytes"] =
      ESP.getFreeHeap();

  doc["firmware_version"] =
      FIRMWARE_VERSION;

  doc["diagnostics"]["bmp280"] =
      bmpReady;

  doc["diagnostics"]["relay_on"] =
      pumpRelayOn;
  doc["diagnostics"]["relay_pump_on"] = pumpRelayOn;
  doc["diagnostics"]["relay_light_on"] = lightRelayOn;
  doc["diagnostics"]["soil_moisture_raw"] = soilRaw;
  doc["diagnostics"]["soil_moisture_percent"] = soilPercent;
  doc["diagnostics"]["wifi_rssi"] = WiFi.RSSI();
  doc["diagnostics"]["firmware_version"] = FIRMWARE_VERSION;
  doc["diagnostics"]["local_ip"] = WiFi.localIP().toString();


  String body;
  String response;

  serializeJson(
      doc,
      body
  );


  int status =
      apiRequest(
          "POST",
          "heartbeat",
          "heartbeat/",
          body,
          response
      );


  if (status >= 0) {

    Serial.printf(
        "heartbeat: HTTP %d\n",
        status
    );
  }
}


// ============================================================
// ACK DE COMANDOS
// ============================================================

void acknowledge(
    const String& id,
    bool succeeded,
    const String& detail,
    bool relayState
) {

  JsonDocument doc;

  doc["status"] =
      succeeded
          ? "succeeded"
          : "failed";

  doc["result"]["relay"] =
      relayState;

  doc["result"]["detail"] =
      detail;


  String body;
  String response;

  serializeJson(
      doc,
      body
  );


  int status =
      apiRequest(
          "POST",
          "commands",
          "commands/"
              + id
              + "/ack/",
          body,
          response
      );


  Serial.printf(
      "ack: HTTP %d\n",
      status
  );
}


// ============================================================
// COMANDOS
// ============================================================

void pollCommands() {

  String response;

  int status =
      apiRequest(
          "GET",
          "commands",
          "commands/",
          "",
          response
      );


  if (status != HTTP_CODE_OK) {

    if (status >= 0) {

      Serial.printf(
          "commands: HTTP %d\n",
          status
      );
    }

    return;
  }


  JsonDocument doc;

  if (deserializeJson(
          doc,
          response
      )) {

    return;
  }


  for (
      JsonObject command :
      doc["commands"].as<JsonArray>()
  ) {

    String id =
        command["id"] | "";

    String channel =
        command["channel"] | "";

    String type =
        command["type"] | "";


    if (
        channel == "pump" &&
        type == "set_state" &&
        command["payload"]["on"].is<bool>()
    ) {

      bool on =
          command["payload"]["on"]
              .as<bool>();

      setPumpState(on);


      uint32_t durationSeconds = command["payload"]["duration_seconds"] | (SAFE_PUMP_DURATION_MS / 1000UL);
      pumpStopAt = on ? millis() + constrain(durationSeconds, 1UL, 300UL) * 1000UL : 0;


      acknowledge(
          id,
          true,
          "relay atualizado",
          pumpRelayOn
      );
    }

    else if (
        channel == "grow-light" &&
        type == "set_state" &&
        command["payload"]["on"].is<bool>()
    ) {
      setLightState(command["payload"]["on"].as<bool>());
      acknowledge(id, true, "iluminacao atualizada", lightRelayOn);
    }
    else {

      acknowledge(
          id,
          false,
          "canal ou comando nao suportado",
          false
      );
    }
  }
}


// ============================================================
// WIFI
// ============================================================

void connectWifi() {

  if (
      WiFi.status() == WL_CONNECTED
  ) {

    return;
  }


  if (
      lastWifiAttemptAt &&
      millis() - lastWifiAttemptAt
          < 10000UL
  ) {

    return;
  }


  lastWifiAttemptAt =
      millis();

  WiFi.mode(WIFI_STA);

  WiFi.reconnect();
}


// ============================================================
// CONFIGURACAO LOCAL
// ============================================================

void saveConfiguration(
    const String& value
) {

  File file =
      LittleFS.open(
          "/device_config.json",
          "w"
      );


  if (!file) {

    return;
  }


  file.print(value);

  file.close();

  cachedConfiguration =
      value;
}


void loadConfiguration() {

  if (!LittleFS.begin()) {

    Serial.println(
        F("Falha ao iniciar LittleFS")
    );

    return;
  }


  File file =
      LittleFS.open(
          "/device_config.json",
          "r"
      );


  if (file) {

    cachedConfiguration =
        file.readString();

    file.close();
  }
}


// ============================================================
// BUSCAR CONFIGURACAO DA PLATAFORMA
// ============================================================

void fetchConfiguration() {

  if (
      WiFi.status() != WL_CONNECTED
  ) {

    return;
  }


  HTTPClient http;

  WiFiClient plain;

  BearSSL::WiFiClientSecure secure;


  String url =
      String(API_BASE_URL)
      + "/api/device/config/";


  bool started =
      false;


  if (url.startsWith("https://")) {

    if (!isTimeSynchronized()) {

      Serial.println(
          F("config: HTTPS adiado; horario ainda nao e valido")
      );

      return;
    }

    printHttpsDiagnostics();

    if (
        strlen(HTTPS_ROOT_CA) < 40
    ) {

      Serial.println(
          F("config: HTTPS_ROOT_CA ausente")
      );

      return;
    }


    static BearSSL::X509List trustAnchor(
        HTTPS_ROOT_CA
    );

    secure.setTrustAnchors(
        &trustAnchor
    );


    started =
        http.begin(
            secure,
            url
        );
  }

  else {

    started =
        http.begin(
            plain,
            url
        );
  }


  if (!started) {

    printRequestError(
        "config",
        http,
        secure,
        HTTPC_ERROR_SEND_HEADER_FAILED
    );

    return;
  }


  http.setTimeout(10000);


  http.addHeader(
      "Authorization",
      String("Device ")
          + DEVICE_API_TOKEN
  );


  http.addHeader(
      "X-Device-ID",
      DEVICE_ID
  );


  int status =
      http.GET();

  if (status < 0) {

    printRequestError(
        "config",
        http,
        secure,
        status
    );
  }


  if (
      status == HTTP_CODE_OK
  ) {

    saveConfiguration(
        http.getString()
    );
  }


  if (status >= 0) {

    Serial.printf(
        "config: HTTP %d\n",
        status
    );
  }


  http.end();
}


// ============================================================
// AUTOMACAO OFFLINE
// ============================================================

void runOfflineAutomation() {
  if (cachedConfiguration.length() < 3 || time(nullptr) < MIN_VALID_EPOCH) return;
  time_t now = time(nullptr);
  struct tm local;
  localtime_r(&now, &local);
  char current[6];
  char bucket[18];
  strftime(current, sizeof(current), "%H:%M", &local);
  strftime(bucket, sizeof(bucket), "%Y%m%d-%H:%M", &local);
  int weekday = (local.tm_wday + 6) % 7;

  JsonDocument doc;
  if (deserializeJson(doc, cachedConfiguration)) return;

  JsonObject irrigation = doc["irrigation"];
  if (!pumpStopAt && (irrigation["enabled"] | false)) {
    bool started = false;
    for (JsonObject schedule : irrigation["schedules"].as<JsonArray>()) {
      bool validDay = false;
      for (JsonVariant day : schedule["days"].as<JsonArray>()) validDay = validDay || day.as<int>() == weekday;
      if ((schedule["enabled"] | true) && validDay && schedule["time"].as<String>() == current && lastIrrigationBucket != bucket) {
        uint32_t duration = constrain(schedule["duration_seconds"] | 10UL, 1UL, 300UL);
        setPumpState(true);
        pumpStopAt = millis() + duration * 1000UL;
        lastIrrigationBucket = bucket;
        started = true;
        break;
      }
    }
    // Compatibilidade com configurações antigas baseadas em times + duration_seconds.
    if (!started) for (JsonVariant value : irrigation["times"].as<JsonArray>()) {
      if (value.as<String>() == current && lastIrrigationBucket != bucket) {
        uint32_t duration = constrain(irrigation["duration_seconds"] | 10UL, 1UL, 300UL);
        setPumpState(true);
        pumpStopAt = millis() + duration * 1000UL;
        lastIrrigationBucket = bucket;
        break;
      }
    }
  }

  JsonObject lighting = doc["lighting"];
  if ((lighting["enabled"] | false) && lastLightingBucket != bucket) {
    int minutesNow = local.tm_hour * 60 + local.tm_min;
    bool shouldBeOn = false;
    for (JsonObject schedule : lighting["schedules"].as<JsonArray>()) {
      if (!(schedule["enabled"] | true)) continue;
      String start = schedule["start"] | "00:00";
      String end = schedule["end"] | "00:00";
      int startMinutes = start.substring(0, 2).toInt() * 60 + start.substring(3).toInt();
      int endMinutes = end.substring(0, 2).toInt() * 60 + end.substring(3).toInt();
      bool today = false, previous = false;
      for (JsonVariant day : schedule["days"].as<JsonArray>()) {
        today = today || day.as<int>() == weekday;
        previous = previous || day.as<int>() == ((weekday + 6) % 7);
      }
      shouldBeOn = shouldBeOn || (startMinutes <= endMinutes
        ? today && minutesNow >= startMinutes && minutesNow < endMinutes
        : (today && minutesNow >= startMinutes) || (previous && minutesNow < endMinutes));
    }
    setLightState(shouldBeOn);
    lastLightingBucket = bucket;
  }
}

} // namespace


// ============================================================
// SETUP
// ============================================================

void setup() {

  Serial.begin(115200);

  delay(500);


  Serial.println();
  Serial.println(
      F("==============================")
  );

  Serial.println(
      F("HORTA INTELIGENTE - ESP8266")
  );

  Serial.println(
      F("==============================")
  );


  // Precarrega o nivel seguro antes de habilitar as saidas, evitando pulsos.
  digitalWrite(PUMP_RELAY_PIN, relayLevel(false, PUMP_RELAY_ACTIVE_LOW));
  digitalWrite(LIGHT_RELAY_PIN, relayLevel(false, LIGHT_RELAY_ACTIVE_LOW));
  pinMode(PUMP_RELAY_PIN, OUTPUT);
  pinMode(LIGHT_RELAY_PIN, OUTPUT);
  setPumpState(false);
  setLightState(false);


  // SDA = D2
  // SCL = D1
  Wire.begin(
      D2,
      D1
  );


  bmpReady =
      bmp.begin(0x76)
      ||
      bmp.begin(0x77);


  Serial.printf(
      "\nBMP280: %s\n",
      bmpReady
          ? "ok"
          : "nao encontrado"
  );


  loadConfiguration();


  // ==========================================================
  // WIFI MANAGER
  // ==========================================================

  WiFiManager manager;


  manager.setConfigPortalTimeout(
      180
  );


  String accessPoint =
      String("Horta-")
      + String(
          ESP.getChipId(),
          HEX
        );


  Serial.print(
      F("Provisionamento Wi-Fi: ")
  );

  Serial.println(
      accessPoint
  );


  if (
      !manager.autoConnect(
          accessPoint.c_str()
      )
  ) {

    Serial.println(
        F(
            "Provisionamento expirou; reiniciando"
        )
    );

    delay(500);

    ESP.restart();
  }


  Serial.println();
  Serial.println(
      F("Wi-Fi conectado!")
  );

  Serial.print(
      F("SSID: ")
  );

  Serial.println(
      WiFi.SSID()
  );

  Serial.print(
      F("IP: ")
  );

  Serial.println(
      WiFi.localIP()
  );


  // Sao Paulo / UTC-3
  configTime(
      -3 * 3600,
      0,
      "pool.ntp.org",
      "time.google.com"
  );

  waitForTimeSynchronization();
}


// ============================================================
// LOOP
// ============================================================

void loop() {

  connectWifi();


  // ==========================================================
  // DESLIGAMENTO DE SEGURANCA DA BOMBA
  // ==========================================================

  if (
      pumpStopAt &&
      static_cast<int32_t>(
          millis() - pumpStopAt
      ) >= 0
  ) {

    setPumpState(false);

    pumpStopAt = 0;

    Serial.println(
        F(
            "Bomba desligada pelo temporizador de seguranca"
        )
    );
  }


  // Automacao continua mesmo sem internet,
  // desde que exista configuracao salva.
  runOfflineAutomation();


  if (
      WiFi.status() != WL_CONNECTED
  ) {

    delay(50);

    return;
  }

  // Certificados TLS so podem ser validados com um relogio valido.
  if (!isTimeSynchronized()) {

    delay(50);

    return;
  }


  uint32_t now =
      millis();


  // ==========================================================
  // TELEMETRIA
  // ==========================================================

  if (
      !lastTelemetryAt ||
      now - lastTelemetryAt
          >= TELEMETRY_INTERVAL_MS
  ) {

    lastTelemetryAt =
        now;

    sendTelemetry();
  }


  // ==========================================================
  // HEARTBEAT
  // ==========================================================

  if (
      !lastHeartbeatAt ||
      now - lastHeartbeatAt
          >= HEARTBEAT_INTERVAL_MS
  ) {

    lastHeartbeatAt =
        now;

    sendHeartbeat();
  }


  // ==========================================================
  // COMANDOS
  // ==========================================================

  if (
      !lastCommandPollAt ||
      now - lastCommandPollAt
          >= COMMAND_POLL_INTERVAL_MS
  ) {

    lastCommandPollAt =
        now;

    pollCommands();
  }


  // ==========================================================
  // CONFIGURACAO
  // ==========================================================

  if (
      !lastConfigPollAt ||
      now - lastConfigPollAt
          >= CONFIG_POLL_INTERVAL_MS
  ) {

    lastConfigPollAt =
        now;

    fetchConfiguration();
  }


  delay(20);
}

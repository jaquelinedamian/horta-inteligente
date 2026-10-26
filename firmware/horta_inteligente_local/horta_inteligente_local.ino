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


// ============================================================
// CONFIGURACAO DA API
// ============================================================

#define API_BASE_URL "https://horta-inteligente.onrender.com"
#define DEVICE_API_TOKEN "feede620f1a8.EWgxQhHqUibzv3yt6_mrQ5od0Mj4NoYaoKUzHXdA59Q"
#define DEVICE_ID "9e14eed7-85aa-4173-b3a8-e0ad5bfdbe2e"

static const char HTTPS_ROOT_CA[] = R"PEM(
-----BEGIN CERTIFICATE-----
MIIDdTCCAl2gAwIBAgILBAAAAAABFUtaw5QwDQYJKoZIhvcNAQEFBQAwVzELMAkGA1UEBhMCQkUx
GTAXBgNVBAoTEEdsb2JhbFNpZ24gbnYtc2ExEDAOBgNVBAsTB1Jvb3QgQ0ExGzAZBgNVBAMTEkds
b2JhbFNpZ24gUm9vdCBDQTAeFw05ODA5MDExMjAwMDBaFw0yODAxMjgxMjAwMDBaMFcxCzAJBgNV
BAYTAkJFMRkwFwYDVQQKExBHbG9iYWxTaWduIG52LXNhMRAwDgYDVQQLEwdSb290IENBMRswGQYD
VQQDExJHbG9iYWxTaWduIFJvb3QgQ0EwggEiMA0GCSqGSIb3DQEBAQUAA4IBDwAwggEKAoIBAQDa
DuaZjc6j40+Kfvvxi4Mla+pIH/EqsLmVEQS98GPR4mdmzxzdzxtIK+6NiY6arymAZavpxy0Sy6sc
THAHoT0KMM0VjU/43dSMUBUc71DuxC73/OlS8pF94G3VNTCOXkNz8kHp1Wrjsok6Vjk4bwY8iGlb
Kk3Fp1S4bInMm/k8yuX9ifUSPJJ4ltbcdG6TRGHRjcdGsnUOhugZitVtbNV4FpWi6cgKOOvyJBNP
c1STE4U6G7weNLWLBYy5d4ux2x8gkasJU26Qzns3dLlwR5EiUWMWea6xrkEmCMgZK9FGqkjWZCrX
gzT/LCrBbBlDSgeF59N89iFo7+ryUp9/k5DPAgMBAAGjQjBAMA4GA1UdDwEB/wQEAwIBBjAPBgNV
HRMBAf8EBTADAQH/MB0GA1UdDgQWBBRge2YaRQ2XyolQL30EzTSo//z9SzANBgkqhkiG9w0BAQUF
AAOCAQEA1nPnfE920I2/7LqivjTFKDK1fPxsnCwrvQmeU79rXqoRSLblCKOzyj1hTdNGCbM+w6Dj
Y1Ub8rrvrTnhQ7k4o+YviiY776BQVvnGCv04zcQLcFGUl5gE38NflNUVyRRBnMRddWQVDf9VMOyG
j/8N7yy5Y0b2qvzfvGn9LhJIZJrglfCm7ymPAbEVtQwdpf5pLGkkeB6zpxxxYu7KyJesF12KwvhH
hm4qxFYxldBniYUr+WymXUadDKqC5JlR3XC321Y9YeRq4VzW9v493kHMB65jUr9TU/Qr6cf9tveC
X4XSQRjbgbMEHMUfpIBvFSDJ3gyICh3WZlXi/EjJKSZp4A==
-----END CERTIFICATE-----
)PEM";

#define TELEMETRY_INTERVAL_MS 60000UL
#define HEARTBEAT_INTERVAL_MS 300000UL
#define COMMAND_POLL_INTERVAL_MS 2000UL
#define SAFE_PUMP_DURATION_MS 10000UL
#define CONFIG_POLL_INTERVAL_MS 30000UL


namespace {

// ============================================================
// PINOS
// ============================================================

constexpr uint8_t PUMP_RELAY_PIN = D5;
constexpr uint8_t LAMP_RELAY_PIN = D6;

// NOVO: sensor de umidade do solo
constexpr uint8_t SOIL_MOISTURE_PIN = A0;

constexpr bool RELAY_ACTIVE_LOW = true;

constexpr char FIRMWARE_VERSION[] =
    "horta-esp8266-1.3.1-platform-lamp";

// ============================================================
// SENSOR / ESTADO
// ============================================================

Adafruit_BMP280 bmp;

bool bmpReady = false;
bool pumpOn = false;
bool lampOn = false;

// NOVO: valor bruto do sensor de umidade
int soilMoistureRaw = 0;

uint32_t sequenceNumber = 0;

uint32_t lastTelemetryAt = 0;
uint32_t lastHeartbeatAt = 0;
uint32_t lastCommandPollAt = 0;
uint32_t lastWifiAttemptAt = 0;
uint32_t lastConfigPollAt = 0;

uint32_t pumpStopAt = 0;
uint32_t lampStopAt = 0;

String cachedConfiguration = "{}";
String lastIrrigationBucket;
String lastLightingBucket;

// ============================================================
// SENSOR DE UMIDADE DO SOLO
// ============================================================
const int SOLO_SECO = 1024;
const int SOLO_MOLHADO = 350;

int soilMoisturePercent = 0;

int readSoilMoisture() {

  soilMoistureRaw =
      analogRead(SOIL_MOISTURE_PIN);

  soilMoisturePercent =
      map(
          soilMoistureRaw,
          SOLO_SECO,
          SOLO_MOLHADO,
          0,
          100
      );

  soilMoisturePercent =
      constrain(
          soilMoisturePercent,
          0,
          100
      );

  Serial.print(
      F("Umidade do solo: ")
  );

  Serial.print(
      soilMoisturePercent
  );

  Serial.print(
      F("% | RAW: ")
  );

  Serial.println(
      soilMoistureRaw
  );

  return soilMoisturePercent;
}

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
// RELES / BOMBA E LAMPADA
// ============================================================

void writeRelay(
    uint8_t pin,
    bool on
) {

  digitalWrite(
      pin,
      (on == RELAY_ACTIVE_LOW)
          ? LOW
          : HIGH
  );
}

void setPump(bool on) {

  pumpOn = on;

  writeRelay(
      PUMP_RELAY_PIN,
      on
  );

  Serial.print(
      F("Bomba: ")
  );

  Serial.println(
      on
          ? F("LIGADA")
          : F("DESLIGADA")
  );
}

void setLamp(bool on) {

  lampOn = on;

  writeRelay(
      LAMP_RELAY_PIN,
      on
  );

  Serial.print(
      F("Lampada: ")
  );

  Serial.println(
      on
          ? F("LIGADA")
          : F("DESLIGADA")
  );
}

// ============================================================
// DATA/HORA
// ============================================================

constexpr time_t MIN_VALID_EPOCH =
    1700000000;

String utcNow();

bool isTimeSynchronized() {

  return
      time(nullptr)
      >= MIN_VALID_EPOCH;
}

bool waitForTimeSynchronization(
    uint32_t timeoutMs = 15000UL
) {

  Serial.println(
      F("Sincronizando horario...")
  );

  const uint32_t startedAt =
      millis();

  while (
      !isTimeSynchronized()
      &&
      millis() - startedAt < timeoutMs
  ) {

    delay(250);

    yield();
  }

  if (!isTimeSynchronized()) {

    Serial.println(
        F(
          "Falha ao sincronizar horario dentro do timeout."
        )
    );

    return false;
  }

  Serial.print(
      F("Horario sincronizado: ")
  );

  Serial.println(
      utcNow()
  );

  return true;
}

String utcNow() {

  time_t now =
      time(nullptr);

  if (now < MIN_VALID_EPOCH) {

    return "";
  }

  struct tm value;

  gmtime_r(
      &now,
      &value
  );

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

String nextKey(
    const char* channel
) {

  return
      String(
          ESP.getChipId(),
          HEX
      )
      + "-"
      + channel
      + "-"
      + String(
          static_cast<uint32_t>(
              time(nullptr)
          )
      )
      + "-"
      + String(
          sequenceNumber++
      );
}

// ============================================================
// HTTP / HTTPS
// ============================================================

void printHttpsDiagnostics() {

  Serial.println(
      F(
        "API host: horta-inteligente.onrender.com"
      )
  );

  Serial.printf(
      "Wi-Fi status: %d (%s)\n",
      WiFi.status(),
      WiFi.status() == WL_CONNECTED
          ? "conectado"
          : "desconectado"
  );

  Serial.print(
      F("IP local: ")
  );

  Serial.println(
      WiFi.localIP()
  );

  Serial.printf(
      "RSSI: %d dBm\n",
      WiFi.RSSI()
  );

  Serial.printf(
      "Hora atual do ESP8266: %ld\n",
      static_cast<long>(
          time(nullptr)
      )
  );
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

  const int sslError =
      secure.getLastSSLError(
          sslMessage,
          sizeof(sslMessage)
      );

  Serial.printf(
      "%s: TLS %d - %s\n",
      channel,
      sslError,
      sslMessage[0]
          ? sslMessage
          : "sem erro SSL registrado"
  );
}

String normalizedDeviceToken() {
  String token = String(DEVICE_API_TOKEN);
  token.trim();
  return token;
}

bool hasValidTokenFormat(const String& token) {
  int dotIndex = token.indexOf('.');

  if (
      dotIndex <= 0
      || dotIndex != token.lastIndexOf('.')
      || dotIndex == token.length() - 1
  ) {
    return false;
  }

  for (unsigned int index = 0; index < token.length(); index++) {
    char value = token.charAt(index);
    bool allowed =
        isAlphaNumeric(value)
        || value == '-'
        || value == '_'
        || value == '.';

    if (!allowed) {
      return false;
    }
  }

  return true;
}

void printAuthDiagnostics(
    const String& token,
    const String& endpoint
) {
  int dotIndex = token.indexOf('.');
  String prefix =
      dotIndex > 0
          ? token.substring(0, dotIndex)
          : String("invalido");

  Serial.println();
  Serial.println(F("===== AUTH DIAGNOSTICS ====="));
  Serial.println(F("AUTH SCHEME: Device"));
  Serial.print(F("TOKEN PREFIX: "));
  Serial.println(prefix);
  Serial.print(F("TOKEN LENGTH: "));
  Serial.println(token.length());
  Serial.print(F("TOKEN HAS DOT: "));
  Serial.println(dotIndex > 0 ? F("SIM") : F("NAO"));
  Serial.print(F("TOKEN FORMAT: "));
  Serial.println(hasValidTokenFormat(token) ? F("VALIDO") : F("INVALIDO"));
  Serial.print(F("DEVICE ID: "));
  Serial.println(DEVICE_ID);
  Serial.print(F("ENDPOINT: "));
  Serial.println(endpoint);
  Serial.print(F("AUTH HEADER LENGTH: "));
  Serial.println(token.length() + strlen("Device "));
  Serial.println(F("============================"));
}

bool addDeviceHeaders(
    HTTPClient& http,
    const String& endpoint
) {
  String token = normalizedDeviceToken();

  printAuthDiagnostics(token, endpoint);

  if (!hasValidTokenFormat(token)) {
    Serial.println(
        F("Requisicao cancelada: formato da credencial invalido")
    );
    return false;
  }

  String authorization = String("Device ") + token;

  http.addHeader("Authorization", authorization);
  http.addHeader("Content-Type", "application/json");
  http.addHeader("Accept", "application/json");
  http.addHeader("X-Device-ID", DEVICE_ID);

  return true;
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

  if (
      url.startsWith(
          "https://"
      )
  ) {

    if (
        !isTimeSynchronized()
    ) {

      Serial.println(
          F(
            "HTTPS adiado: horario do ESP8266 ainda nao e valido"
          )
      );

      return false;
    }

    printHttpsDiagnostics();

    if (
        strlen(HTTPS_ROOT_CA)
        < 40
    ) {

      Serial.println(
          F(
            "HTTPS_ROOT_CA ausente; HTTPS cancelado"
          )
      );

      return false;
    }

    static BearSSL::X509List
        trustAnchor(
            HTTPS_ROOT_CA
        );

    secure.setTrustAnchors(
        &trustAnchor
    );

    if (
        !http.begin(
            secure,
            url
        )
    ) {

      return false;
    }

  } else {

    if (
        !http.begin(
            plain,
            url
        )
    ) {

      return false;
    }
  }

  http.setTimeout(
      70000
  );

  return addDeviceHeaders(http, url);
}

int apiRequest(
    const char* method,
    const char* channel,
    const String& path,
    const String& body,
    String& response
) {

  if (
      WiFi.status()
      != WL_CONNECTED
  ) {

    return -1;
  }

  HTTPClient http;

  WiFiClient plain;

  BearSSL::WiFiClientSecure
      secure;

  if (
      !beginHttp(
          http,
          plain,
          secure,
          path
      )
  ) {

    printRequestError(
        channel,
        http,
        secure,
        HTTPC_ERROR_SEND_HEADER_FAILED
    );

    return -2;
  }

  int status;

  if (
      strcmp(
          method,
          "GET"
      )
      == 0
  ) {

    status =
        http.GET();

  } else {

    status =
        http.POST(
            body
        );
  }

  if (
      status > 0
  ) {

    response =
        http.getString();

  } else {

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

  String recordedAt =
      utcNow();

  if (
      recordedAt.isEmpty()
  ) {

    return;
  }

  // ==========================================================
  // NOVO: LER A UMIDADE DO SOLO
  // ==========================================================

  int moisture =
      readSoilMoisture();

  // ==========================================================
  // BMP280
  // ==========================================================

  float temperature =
      NAN;

  float pressure =
      NAN;

  if (bmpReady) {

    temperature =
        bmp.readTemperature();

    pressure =
        bmp.readPressure()
        / 100.0F;
  }

  // ==========================================================
  // EXIBIR SENSORES NO MONITOR SERIAL
  // ==========================================================

  Serial.println();
  Serial.println(
      F("===== SENSORES =====")
  );

  if (
      bmpReady
      &&
      isfinite(temperature)
  ) {

    Serial.print(
        F("Temperatura: ")
    );

    Serial.print(
        temperature,
        1
    );

    Serial.println(
        F(" C")
    );

  } else {

    Serial.println(
        F("Temperatura: indisponivel")
    );
  }

  if (
      bmpReady
      &&
      isfinite(pressure)
  ) {

    Serial.print(
        F("Pressao: ")
    );

    Serial.print(
        pressure,
        1
    );

    Serial.println(
        F(" hPa")
    );

  } else {

    Serial.println(
        F("Pressao: indisponivel")
    );
  }

  Serial.print(
      F("Umidade do solo: ")
  );

  Serial.print(
      moisture
  );

  Serial.print(
      F("% | RAW: ")
  );

  Serial.println(
      soilMoistureRaw
  );

  Serial.print(
      F("Bomba: ")
  );

  Serial.println(
      pumpOn
          ? F("LIGADA")
          : F("DESLIGADA")
  );

  Serial.print(
      F("Lampada: ")
  );

  Serial.println(
      lampOn
          ? F("LIGADA")
          : F("DESLIGADA")
  );

  Serial.println(
      F("====================")
  );

  JsonDocument doc;

  JsonArray readings =
      doc["readings"]
          .to<JsonArray>();

  // ==========================================================
  // TEMPERATURA
  // ==========================================================

  if (
      bmpReady
      &&
      isfinite(temperature)
  ) {

    JsonObject temperatureItem =
        readings.add<JsonObject>();

    temperatureItem["channel"] =
        "air-temperature";

    temperatureItem["value"] =
        temperature;

    temperatureItem["recorded_at"] =
        recordedAt;

    temperatureItem["idempotency_key"] =
        nextKey(
            "temperature"
        );
  }

  // ==========================================================
  // PRESSAO
  // ==========================================================

  if (
      bmpReady
      &&
      isfinite(pressure)
  ) {

    JsonObject pressureItem =
        readings.add<JsonObject>();

    pressureItem["channel"] =
        "air-pressure";

    pressureItem["value"] =
        pressure;

    pressureItem["recorded_at"] =
        recordedAt;

    pressureItem["idempotency_key"] =
        nextKey(
            "pressure"
        );
  }

  // ==========================================================
  // UMIDADE DO SOLO
  // ==========================================================
  //
  // Envia a porcentagem calculada para o canal soil-moisture.
  // Os valores SOLO_SECO e SOLO_MOLHADO devem ser calibrados
  // com o sensor instalado na horta para melhorar a precisao.
  // ==========================================================

  Serial.printf(
      "Umidade do solo preparada para envio: %d%% | RAW: %d\n",
      moisture,
      soilMoistureRaw
  );

  JsonObject moistureItem =
      readings.add<JsonObject>();

  moistureItem["channel"] =
      "soil-moisture";

  moistureItem["value"] =
      moisture;

  moistureItem["recorded_at"] =
      recordedAt;

  moistureItem["idempotency_key"] =
      nextKey(
          "soil-moisture"
      );

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

  if (
      status >= 0
  ) {

    Serial.printf(
        "telemetry: HTTP %d\n",
        status
    );

    if (
        status
        == HTTP_CODE_BAD_REQUEST
    ) {

      JsonDocument
          errorDocument;

      DeserializationError
          error =
              deserializeJson(
                  errorDocument,
                  response
              );

      if (
          !error
          &&
          errorDocument["detail"]
              .is<const char*>()
      ) {

        Serial.print(
            F(
              "telemetry: detail: "
            )
        );

        Serial.println(
            errorDocument["detail"]
                .as<const char*>()
        );

      } else {

        Serial.print(
            F(
              "telemetry: resposta: "
            )
        );

        Serial.println(
            response
        );
      }
    }
  }
}

// ============================================================
// HEARTBEAT
// ============================================================

void sendHeartbeat() {

  String recordedAt =
      utcNow();

  if (
      recordedAt.isEmpty()
  ) {

    return;
  }

  JsonDocument doc;

  doc["recorded_at"] =
      recordedAt;

  doc["uptime_seconds"] =
      millis()
      / 1000UL;

  doc["signal_strength"] =
      WiFi.RSSI();

  doc["free_heap_bytes"] =
      ESP.getFreeHeap();

  doc["firmware_version"] =
      FIRMWARE_VERSION;

  doc["diagnostics"]["bmp280"] =
      bmpReady;

  doc["diagnostics"]["pump_on"] =
      pumpOn;

  doc["diagnostics"]["lamp_on"] =
      lampOn;

  // NOVO
  doc["diagnostics"]["soil_moisture_raw"] =
      soilMoistureRaw;

  doc["diagnostics"]["soil_moisture_percent"] =
      soilMoisturePercent;

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

  if (
      status >= 0
  ) {

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
    const String& detail
) {

  JsonDocument doc;

  doc["status"] =
      succeeded
          ? "succeeded"
          : "failed";

  doc["result"]["pump"] =
      pumpOn;

  doc["result"]["lamp"] =
      lampOn;

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

  if (
      status
      != HTTP_CODE_OK
  ) {

    if (
        status >= 0
    ) {

      Serial.printf(
          "commands: HTTP %d\n",
          status
      );
    }

    return;
  }

  JsonDocument doc;

  if (
      deserializeJson(
          doc,
          response
      )
  ) {

    return;
  }

  for (
      JsonObject command :
      doc["commands"]
          .as<JsonArray>()
  ) {

    String id =
        command["id"]
        | "";

    String channel =
        command["channel"]
        | "";

    String type =
        command["type"]
        | "";

    if (
        type != "set_state"
        ||
        !command["payload"]["on"]
            .is<bool>()
    ) {

      acknowledge(
          id,
          false,
          "tipo de comando nao suportado"
      );

      continue;
    }

    bool on =
        command["payload"]["on"]
            .as<bool>();

    // Diagnostico: mostra no Serial todo comando recebido da plataforma.
    Serial.print(F("Comando da plataforma | canal: "));
    Serial.print(channel);
    Serial.print(F(" | estado: "));
    Serial.println(on ? F("LIGAR") : F("DESLIGAR"));

    String mode =
        command["payload"]["mode"]
        | "";

    uint32_t durationSeconds =
        command["payload"]["duration_seconds"]
        | 0UL;

    // ----------------------------------------------------------
    // BOMBA
    // ----------------------------------------------------------

    if (
        channel == "pump"
    ) {

      setPump(
          on
      );

      if (!on) {

        pumpStopAt =
            0;

      } else if (
          durationSeconds > 0
      ) {

        durationSeconds =
            constrain(
                durationSeconds,
                1UL,
                300UL
            );

        pumpStopAt =
            millis()
            +
            durationSeconds
            * 1000UL;

      } else if (
          mode == "safe_preset"
      ) {

        pumpStopAt =
            millis()
            +
            SAFE_PUMP_DURATION_MS;

      } else {

        // Ligada manualmente sem temporizador.
        // Permanecera ligada ate receber comando OFF.
        pumpStopAt =
            0;
      }

      acknowledge(
          id,
          true,
          on
              ? "bomba ligada"
              : "bomba desligada"
      );

    // ----------------------------------------------------------
    // LAMPADA
    // ----------------------------------------------------------

    } else if (
        channel == "lamp"
    ) {

      Serial.println(F("Executando comando da LAMPADA recebido pela plataforma..."));

      setLamp(
          on
      );

      Serial.print(F("Estado fisico solicitado para a lampada no D6: "));
      Serial.println(on ? F("LIGADA") : F("DESLIGADA"));

      if (!on) {

        lampStopAt =
            0;

      } else if (
          durationSeconds > 0
      ) {

        durationSeconds =
            constrain(
                durationSeconds,
                1UL,
                86400UL
            );

        lampStopAt =
            millis()
            +
            durationSeconds
            * 1000UL;

      } else {

        // Ligada manualmente sem temporizador.
        // Permanecera ligada ate receber comando OFF.
        lampStopAt =
            0;
      }

      acknowledge(
          id,
          true,
          on
              ? "lampada ligada"
              : "lampada desligada"
      );

    } else {

      acknowledge(
          id,
          false,
          "canal nao suportado"
      );
    }
  }
}

// ============================================================
// WIFI
// ============================================================

void connectWifi() {

  if (
      WiFi.status()
      == WL_CONNECTED
  ) {

    return;
  }

  if (
      lastWifiAttemptAt
      &&
      millis()
          - lastWifiAttemptAt
          < 10000UL
  ) {

    return;
  }

  lastWifiAttemptAt =
      millis();

  WiFi.mode(
      WIFI_STA
  );

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

  file.print(
      value
  );

  file.close();

  cachedConfiguration =
      value;
}

void loadConfiguration() {

  if (
      !LittleFS.begin()
  ) {

    Serial.println(
        F(
          "Falha ao iniciar LittleFS"
        )
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
      WiFi.status()
      != WL_CONNECTED
  ) {

    return;
  }

  HTTPClient http;

  WiFiClient plain;

  BearSSL::WiFiClientSecure
      secure;

  String url =
      String(API_BASE_URL)
      + "/api/device/config/";

  bool started =
      false;

  if (
      url.startsWith(
          "https://"
      )
  ) {

    if (
        !isTimeSynchronized()
    ) {

      Serial.println(
          F(
            "config: HTTPS adiado; horario ainda nao e valido"
          )
      );

      return;
    }

    printHttpsDiagnostics();

    if (
        strlen(
            HTTPS_ROOT_CA
        )
        < 40
    ) {

      Serial.println(
          F(
            "config: HTTPS_ROOT_CA ausente"
          )
      );

      return;
    }

    static BearSSL::X509List
        trustAnchor(
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

  } else {

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

  http.setTimeout(
      70000
  );

  if (!addDeviceHeaders(http, url)) {
    http.end();
    return;
  }

  int status =
      http.GET();

  if (
      status < 0
  ) {

    printRequestError(
        "config",
        http,
        secure,
        status
    );
  }

  if (
      status
      == HTTP_CODE_OK
  ) {

    saveConfiguration(
        http.getString()
    );
  }

  if (
      status >= 0
  ) {

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

// Retorna a duracao configurada pela plataforma.
// Aceita:
//   duration_seconds
//   duration_minutes
//   duration_hours
uint32_t readDurationSeconds(
    JsonObject config,
    uint32_t defaultSeconds,
    uint32_t maxSeconds
) {

  uint32_t duration =
      defaultSeconds;

  if (
      config["duration_seconds"]
          .is<uint32_t>()
  ) {

    duration =
        config["duration_seconds"]
            .as<uint32_t>();

  } else if (
      config["duration_minutes"]
          .is<uint32_t>()
  ) {

    duration =
        config["duration_minutes"]
            .as<uint32_t>()
        * 60UL;

  } else if (
      config["duration_hours"]
          .is<uint32_t>()
  ) {

    duration =
        config["duration_hours"]
            .as<uint32_t>()
        * 3600UL;
  }

  return constrain(
      duration,
      1UL,
      maxSeconds
  );
}

bool scheduleMatchesNow(
    JsonObject config,
    const char* current
) {

  if (
      !(
          config["enabled"]
          | false
      )
  ) {

    return false;
  }

  JsonArray times =
      config["times"]
          .as<JsonArray>();

  if (times.isNull()) {

    return false;
  }

  for (
      JsonVariant value :
      times
  ) {

    if (
        value.as<String>()
        == current
    ) {

      return true;
    }
  }

  return false;
}

void runOfflineAutomation() {

  if (
      cachedConfiguration.length()
      < 3
  ) {

    return;
  }

  time_t now =
      time(nullptr);

  if (
      now
      < MIN_VALID_EPOCH
  ) {

    return;
  }

  struct tm local;

  localtime_r(
      &now,
      &local
  );

  char current[6];

  char bucket[18];

  strftime(
      current,
      sizeof(current),
      "%H:%M",
      &local
  );

  strftime(
      bucket,
      sizeof(bucket),
      "%Y%m%d-%H:%M",
      &local
  );

  JsonDocument doc;

  if (
      deserializeJson(
          doc,
          cachedConfiguration
      )
  ) {

    return;
  }

  // ==========================================================
  // BOMBA / IRRIGACAO
  //
  // Exemplo de configuracao recebida da plataforma:
  //
  // "irrigation": {
  //   "enabled": true,
  //   "times": ["07:00", "18:00"],
  //   "duration_seconds": 15
  // }
  // ==========================================================

  JsonObject irrigation =
      doc["irrigation"];

  if (
      !pumpOn
      &&
      scheduleMatchesNow(
          irrigation,
          current
      )
      &&
      lastIrrigationBucket
          != bucket
  ) {

    uint32_t duration =
        readDurationSeconds(
            irrigation,
            SAFE_PUMP_DURATION_MS
                / 1000UL,
            300UL
        );

    setPump(
        true
    );

    pumpStopAt =
        millis()
        +
        duration
        * 1000UL;

    lastIrrigationBucket =
        bucket;

    Serial.printf(
        "Irrigacao iniciada: %lu segundos\n",
        static_cast<unsigned long>(
            duration
        )
    );
  }

  // ==========================================================
  // LAMPADA / ILUMINACAO
  //
  // Exemplo de configuracao recebida da plataforma:
  //
  // "lighting": {
  //   "enabled": true,
  //   "times": ["06:00"],
  //   "duration_hours": 12
  // }
  //
  // Tambem aceita duration_seconds ou duration_minutes.
  // ==========================================================

  JsonObject lighting =
      doc["lighting"];

  if (
      !lampOn
      &&
      scheduleMatchesNow(
          lighting,
          current
      )
      &&
      lastLightingBucket
          != bucket
  ) {

    uint32_t duration =
        readDurationSeconds(
            lighting,
            3600UL,
            86400UL
        );

    setLamp(
        true
    );

    lampStopAt =
        millis()
        +
        duration
        * 1000UL;

    lastLightingBucket =
        bucket;

    Serial.printf(
        "Iluminacao iniciada: %lu segundos\n",
        static_cast<unsigned long>(
            duration
        )
    );
  }
}

} // namespace

// ============================================================
// SETUP
// ============================================================

void setup() {

  Serial.begin(
      115200
  );

  delay(
      500
  );

  Serial.println();

  Serial.println(
      F(
        "=============================="
      )
  );

  Serial.println(
      F(
        "HORTA INTELIGENTE - ESP8266"
      )
  );

  Serial.println(
      F(
        "=============================="
      )
  );

  pinMode(
      PUMP_RELAY_PIN,
      OUTPUT
  );

  pinMode(
      LAMP_RELAY_PIN,
      OUTPUT
  );

  // Os dois relés iniciam desligados.
  // A plataforma ou a programação salva decide quando ligar.
  setPump(
      false
  );

  setLamp(
      false
  );

  // SDA = D2
  // SCL = D1
  Wire.begin(
      D2,
      D1
  );

  bmpReady =
      bmp.begin(
          0x76
      )
      ||
      bmp.begin(
          0x77
      );

  Serial.printf(
      "\nBMP280: %s\n",
      bmpReady
          ? "ok"
          : "nao encontrado"
  );

  // ==========================================================
  // NOVO: PRIMEIRA LEITURA DO SENSOR DE SOLO
  // ==========================================================

  Serial.println(
      F(
        "Testando sensor de umidade do solo..."
      )
  );

  readSoilMoisture();

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
      +
      String(
          ESP.getChipId(),
          HEX
      );

  Serial.print(
      F(
        "Provisionamento Wi-Fi: "
      )
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

    delay(
        500
    );

    ESP.restart();
  }

  Serial.println();

  Serial.println(
      F(
        "Wi-Fi conectado!"
      )
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

  Serial.println();
  Serial.println(
      F("Configuracao da plataforma: atualizacao a cada 30 segundos")
  );
  Serial.println(
      F("Telemetria dos sensores: envio a cada 60 segundos")
  );
  Serial.println(
      F("Controle da lampada: plataforma -> canal lamp -> D6")
  );
  Serial.println(
      F("Comandos da plataforma: consulta a cada 2 segundos")
  );
}

// ============================================================
// LOOP
// ============================================================

void loop() {

  connectWifi();

  // ==========================================================
  // TEMPORIZADOR DA BOMBA
  // ==========================================================

  if (
      pumpStopAt
      &&
      static_cast<int32_t>(
          millis()
          - pumpStopAt
      )
      >= 0
  ) {

    setPump(
        false
    );

    pumpStopAt =
        0;

    Serial.println(
        F(
          "Bomba desligada pelo temporizador"
        )
    );
  }

  // ==========================================================
  // TEMPORIZADOR DA LAMPADA
  // ==========================================================

  if (
      lampStopAt
      &&
      static_cast<int32_t>(
          millis()
          - lampStopAt
      )
      >= 0
  ) {

    setLamp(
        false
    );

    lampStopAt =
        0;

    Serial.println(
        F(
          "Lampada desligada pelo temporizador"
        )
    );
  }

  // Automacao continua mesmo sem internet,
  // desde que exista configuracao salva.
  runOfflineAutomation();

  if (
      WiFi.status()
      != WL_CONNECTED
  ) {

    delay(
        50
    );

    return;
  }

  if (
      !isTimeSynchronized()
  ) {

    delay(
        50
    );

    return;
  }

  uint32_t now =
      millis();

  // ==========================================================
  // TELEMETRIA
  // ==========================================================

  if (
      !lastTelemetryAt
      ||
      now
          - lastTelemetryAt
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
      !lastHeartbeatAt
      ||
      now
          - lastHeartbeatAt
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
      !lastCommandPollAt
      ||
      now
          - lastCommandPollAt
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
      !lastConfigPollAt
      ||
      now
          - lastConfigPollAt
          >= CONFIG_POLL_INTERVAL_MS
  ) {

    lastConfigPollAt =
        now;

    fetchConfiguration();
  }

  delay(
      20
  );
}

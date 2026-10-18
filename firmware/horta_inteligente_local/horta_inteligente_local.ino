#include <ESP8266WiFi.h>
#include <ESP8266WebServer.h>
#include <Wire.h>
#include <Adafruit_Sensor.h>
#include <Adafruit_BMP280.h>

// ============================================================
// CONFIGURACAO DO WI-FI
// ============================================================
const char* WIFI_SSID = "NOME_DA_REDE";
const char* WIFI_SENHA = "SENHA_DA_REDE";

// ============================================================
// CONFIGURACOES
// ============================================================
constexpr uint8_t ENDERECO_BMP280 = 0x76;

constexpr unsigned long INTERVALO_LEITURA_MS = 3000;
constexpr unsigned long INTERVALO_RECONEXAO_MS = 10000;

// Sensor de umidade ligado no A0 do Wemos
constexpr uint8_t PINO_UMIDADE = A0;

ESP8266WebServer servidor(80);
Adafruit_BMP280 bmp;

// ============================================================
// ESTADO DOS SENSORES
// ============================================================
bool sensorOnline = false;

float temperatura = NAN;
float pressao = NAN;

// valor bruto do sensor de umidade: normalmente entre 0 e 1023
int umidadeSoloRaw = 0;

unsigned long ultimaLeitura = 0;
unsigned long ultimaTentativaWifi = 0;
unsigned long ultimaTentativaSensor = 0;

// ============================================================
// WIFI
// ============================================================
void conectarWifi() {
  Serial.printf("Conectando a rede %s", WIFI_SSID);

  WiFi.mode(WIFI_STA);
  WiFi.persistent(false);
  WiFi.setAutoReconnect(true);

  WiFi.begin(WIFI_SSID, WIFI_SENHA);

  unsigned long inicio = millis();

  while (
    WiFi.status() != WL_CONNECTED &&
    millis() - inicio < 20000
  ) {
    delay(500);
    Serial.print('.');
  }

  if (WiFi.status() == WL_CONNECTED) {
    Serial.println("\nWi-Fi conectado!");

    Serial.print("Endereco IP: http://");
    Serial.println(WiFi.localIP());

  } else {
    Serial.println(
      "\nWi-Fi ainda desconectado. Novas tentativas serao feitas."
    );
  }
}

void verificarWifi() {
  if (WiFi.status() == WL_CONNECTED) {
    return;
  }

  if (
    millis() - ultimaTentativaWifi <
    INTERVALO_RECONEXAO_MS
  ) {
    return;
  }

  ultimaTentativaWifi = millis();

  Serial.println(
    "Wi-Fi desconectado. Tentando reconectar..."
  );

  WiFi.disconnect();
  WiFi.begin(WIFI_SSID, WIFI_SENHA);
}

// ============================================================
// BMP280
// ============================================================
bool iniciarSensor() {
  sensorOnline = bmp.begin(ENDERECO_BMP280);

  Serial.println(
    sensorOnline
      ? "BMP280 online no endereco 0x76."
      : "BMP280 offline. Verifique fios e alimentacao."
  );

  return sensorOnline;
}

// ============================================================
// SENSOR DE UMIDADE DO SOLO
// ============================================================
void lerUmidadeSolo() {
  umidadeSoloRaw = analogRead(PINO_UMIDADE);

  Serial.print("Umidade do solo RAW: ");
  Serial.println(umidadeSoloRaw);
}

// ============================================================
// LEITURA BMP280
// ============================================================
void lerSensor() {
  if (!sensorOnline) {

    if (
      millis() - ultimaTentativaSensor >=
      INTERVALO_RECONEXAO_MS
    ) {
      ultimaTentativaSensor = millis();
      iniciarSensor();
    }

    return;
  }

  float novaTemperatura =
    bmp.readTemperature();

  float novaPressao =
    bmp.readPressure() / 100.0F;

  if (
    !isfinite(novaTemperatura) ||
    !isfinite(novaPressao)
  ) {

    sensorOnline = false;
    temperatura = NAN;
    pressao = NAN;

    Serial.println(
      "Falha ao ler o BMP280. Sensor marcado como offline."
    );

    return;
  }

  temperatura = novaTemperatura;
  pressao = novaPressao;

  Serial.printf(
    "Temperatura: %.1f C | Pressao: %.1f hPa\n",
    temperatura,
    pressao
  );
}

// ============================================================
// ENDPOINT /dados
// ============================================================
void responderDados() {

  String json;

  json.reserve(180);

  json = "{";

  // temperatura
  if (
    sensorOnline &&
    isfinite(temperatura)
  ) {
    json += "\"temperatura\":";
    json += String(temperatura, 1);
  } else {
    json += "\"temperatura\":null";
  }

  // pressao
  json += ",";

  if (
    sensorOnline &&
    isfinite(pressao)
  ) {
    json += "\"pressao\":";
    json += String(pressao, 1);
  } else {
    json += "\"pressao\":null";
  }

  // umidade do solo
  json += ",\"umidade_solo_raw\":";
  json += String(umidadeSoloRaw);

  // status
  json += ",\"sensor_bmp280\":\"";
  json += sensorOnline ? "online" : "offline";
  json += "\"";

  json += ",\"wifi\":\"";
  json += (
    WiFi.status() == WL_CONNECTED
      ? "online"
      : "offline"
  );
  json += "\"";

  json += "}";

  servidor.sendHeader(
    "Access-Control-Allow-Origin",
    "*"
  );

  servidor.sendHeader(
    "Cache-Control",
    "no-store"
  );

  servidor.send(
    200,
    "application/json; charset=utf-8",
    json
  );
}

// ============================================================
// SETUP
// ============================================================
void setup() {

  Serial.begin(115200);

  Serial.println();
  Serial.println();
  Serial.println(
    "Iniciando Horta Inteligente..."
  );

  // BMP280
  Wire.begin(
    D2, // SDA
    D1  // SCL
  );

  iniciarSensor();

  // Sensor de umidade
  lerUmidadeSolo();

  // Wi-Fi
  conectarWifi();

  // Servidor
  servidor.on(
    "/dados",
    HTTP_GET,
    responderDados
  );

  servidor.onNotFound([]() {
    servidor.send(
      404,
      "text/plain; charset=utf-8",
      "Pagina nao encontrada"
    );
  });

  servidor.begin();

  Serial.println(
    "Servidor web iniciado na porta 80."
  );

  lerSensor();

  ultimaLeitura = millis();
}

// ============================================================
// LOOP
// ============================================================
void loop() {

  servidor.handleClient();

  verificarWifi();

  if (
    millis() - ultimaLeitura >=
    INTERVALO_LEITURA_MS
  ) {

    ultimaLeitura = millis();

    // lê os dois sensores independentemente
    lerSensor();
    lerUmidadeSolo();
  }

  yield();
}
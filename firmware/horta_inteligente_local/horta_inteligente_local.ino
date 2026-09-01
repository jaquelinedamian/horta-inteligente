#include <ESP8266WiFi.h>
#include <ESP8266WebServer.h>
#include <Wire.h>
#include <Adafruit_Sensor.h>
#include <Adafruit_BMP280.h>

// ============================================================
// CONFIGURACAO DO WI-FI
// Troque somente os dois valores abaixo pelos dados da sua rede.
// ============================================================
const char* WIFI_SSID = "NOME_DA_REDE";
const char* WIFI_SENHA = "SENHA_DA_REDE";

constexpr uint8_t ENDERECO_BMP280 = 0x76;
constexpr unsigned long INTERVALO_LEITURA_MS = 3000;
constexpr unsigned long INTERVALO_RECONEXAO_MS = 10000;

ESP8266WebServer servidor(80);
Adafruit_BMP280 bmp;

bool sensorOnline = false;
float temperatura = NAN;
float pressao = NAN;
unsigned long ultimaLeitura = 0;
unsigned long ultimaTentativaWifi = 0;
unsigned long ultimaTentativaSensor = 0;

void conectarWifi() {
  Serial.printf("Conectando a rede %s", WIFI_SSID);
  WiFi.mode(WIFI_STA);
  WiFi.persistent(false);
  WiFi.setAutoReconnect(true);
  WiFi.begin(WIFI_SSID, WIFI_SENHA);

  // Aguarda somente no boot. Depois, as reconexoes nao bloqueiam o servidor.
  unsigned long inicio = millis();
  while (WiFi.status() != WL_CONNECTED && millis() - inicio < 20000) {
    delay(500);
    Serial.print('.');
  }

  if (WiFi.status() == WL_CONNECTED) {
    Serial.println("\nWi-Fi conectado!");
    Serial.print("Endereco IP: http://");
    Serial.println(WiFi.localIP());
  } else {
    Serial.println("\nWi-Fi ainda desconectado. Novas tentativas serao feitas.");
  }
}

void verificarWifi() {
  if (WiFi.status() == WL_CONNECTED) return;
  if (millis() - ultimaTentativaWifi < INTERVALO_RECONEXAO_MS) return;

  ultimaTentativaWifi = millis();
  Serial.println("Wi-Fi desconectado. Tentando reconectar...");
  WiFi.disconnect();
  WiFi.begin(WIFI_SSID, WIFI_SENHA);
}

bool iniciarSensor() {
  sensorOnline = bmp.begin(ENDERECO_BMP280);
  Serial.println(sensorOnline ? "BMP280 online no endereco 0x76."
                              : "BMP280 offline. Verifique fios e alimentacao.");
  return sensorOnline;
}

void lerSensor() {
  if (!sensorOnline) {
    // Permite que o sensor volte a funcionar sem reiniciar o ESP8266.
    if (millis() - ultimaTentativaSensor >= INTERVALO_RECONEXAO_MS) {
      ultimaTentativaSensor = millis();
      iniciarSensor();
    }
    return;
  }

  float novaTemperatura = bmp.readTemperature();
  float novaPressao = bmp.readPressure() / 100.0F;  // Pa para hPa

  if (!isfinite(novaTemperatura) || !isfinite(novaPressao)) {
    sensorOnline = false;
    temperatura = NAN;
    pressao = NAN;
    Serial.println("Falha ao ler o BMP280. Sensor marcado como offline.");
    return;
  }

  temperatura = novaTemperatura;
  pressao = novaPressao;
  Serial.printf("Temperatura: %.1f °C | Pressao: %.1f hPa\n", temperatura, pressao);
}

void responderDados() {
  String json;
  if (sensorOnline && isfinite(temperatura) && isfinite(pressao)) {
    json.reserve(100);
    json = "{\"temperatura\":" + String(temperatura, 1) +
           ",\"pressao\":" + String(pressao, 1) +
           ",\"sensor\":\"online\",\"wifi\":\"online\"}";
  } else {
    // null mantem o JSON valido quando nao existe uma leitura confiavel.
    json = "{\"temperatura\":null,\"pressao\":null,\"sensor\":\"offline\",\"wifi\":\"online\"}";
  }
  servidor.sendHeader("Access-Control-Allow-Origin", "*");
  servidor.sendHeader("Cache-Control", "no-store");
  servidor.send(200, "application/json; charset=utf-8", json);
}

void setup() {
  Serial.begin(115200);
  Serial.println("\n\nIniciando Horta Inteligente...");

  Wire.begin(D2, D1);  // SDA = D2, SCL = D1
  iniciarSensor();     // BMP280 no endereco 0x76
  conectarWifi();

  servidor.on("/dados", HTTP_GET, responderDados);
  servidor.onNotFound([]() {
    servidor.send(404, "text/plain; charset=utf-8", "Pagina nao encontrada");
  });
  servidor.begin();
  Serial.println("Servidor web iniciado na porta 80.");

  lerSensor();
  ultimaLeitura = millis();
}

void loop() {
  servidor.handleClient();
  verificarWifi();

  if (millis() - ultimaLeitura >= INTERVALO_LEITURA_MS) {
    ultimaLeitura = millis();
    lerSensor();
  }

  // Entrega tempo ao sistema Wi-Fi do ESP8266.
  yield();
}

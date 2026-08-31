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

// A pagina fica na memoria flash para economizar RAM do ESP8266.
const char PAGINA_HTML[] PROGMEM = R"HTML(
<!doctype html>
<html lang="pt-BR">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <title>Horta Inteligente</title>
  <style>
    :root{color-scheme:light;--verde:#277548;--fundo:#f1f7f2;--texto:#173422}
    *{box-sizing:border-box}
    body{margin:0;min-height:100vh;display:grid;place-items:center;padding:20px;
      background:linear-gradient(145deg,#e5f3e8,#f8fbf7);color:var(--texto);
      font-family:system-ui,-apple-system,"Segoe UI",sans-serif}
    main{width:min(760px,100%)}
    header{text-align:center;margin-bottom:24px}
    h1{margin:0 0 8px;font-size:clamp(2rem,8vw,3.2rem);color:var(--verde)}
    header p{margin:0;color:#627267}
    .grade{display:grid;grid-template-columns:repeat(2,1fr);gap:16px}
    .card{background:#fff;border:1px solid #dce9df;border-radius:20px;padding:24px;
      box-shadow:0 12px 30px rgba(28,78,45,.09)}
    .rotulo{display:block;color:#68796d;font-size:.9rem;margin-bottom:10px}
    .valor{font-size:clamp(2rem,10vw,3.5rem);font-weight:750;line-height:1}
    .unidade{font-size:1rem;font-weight:600;color:#6f7e73;margin-left:4px}
    .status{margin-top:16px;display:flex;flex-wrap:wrap;gap:10px;justify-content:center}
    .selo{background:#fff;border-radius:999px;padding:8px 13px;box-shadow:0 4px 14px #1c4e2d12}
    .ponto{display:inline-block;width:9px;height:9px;border-radius:50%;margin-right:7px;background:#df4c4c}
    .online .ponto{background:#2ca35c}
    .erro{color:#a32f2f}
    footer{text-align:center;color:#718076;font-size:.8rem;margin-top:18px}
    @media(max-width:520px){.grade{grid-template-columns:1fr}.card{padding:20px}}
  </style>
</head>
<body>
  <main>
    <header><h1>Horta Inteligente</h1><p>Monitoramento local do ambiente</p></header>
    <section class="grade">
      <article class="card">
        <span class="rotulo">Temperatura</span>
        <span id="temperatura" class="valor">--</span><span class="unidade">°C</span>
      </article>
      <article class="card">
        <span class="rotulo">Pressao atmosferica</span>
        <span id="pressao" class="valor">--</span><span class="unidade">hPa</span>
      </article>
    </section>
    <section class="status">
      <span id="sensor" class="selo"><i class="ponto"></i>Sensor offline</span>
      <span id="wifi" class="selo online"><i class="ponto"></i>Wi-Fi conectado</span>
    </section>
    <footer>Atualizacao automatica a cada 3 segundos</footer>
  </main>
  <script>
    const temperatura = document.getElementById('temperatura');
    const pressao = document.getElementById('pressao');
    const sensor = document.getElementById('sensor');
    const wifi = document.getElementById('wifi');

    async function atualizarDados() {
      try {
        const resposta = await fetch('/dados', {cache: 'no-store'});
        if (!resposta.ok) throw new Error('Resposta invalida');
        const dados = await resposta.json();
        const online = dados.sensor === 'online';
        temperatura.textContent = online ? dados.temperatura.toFixed(1) : '--';
        pressao.textContent = online ? dados.pressao.toFixed(1) : '--';
        sensor.className = 'selo ' + (online ? 'online' : 'erro');
        sensor.innerHTML = '<i class="ponto"></i>' + (online ? 'Sensor online' : 'Sensor offline');
        wifi.className = 'selo online';
        wifi.innerHTML = '<i class="ponto"></i>Wi-Fi conectado';
      } catch (erro) {
        wifi.className = 'selo erro';
        wifi.innerHTML = '<i class="ponto"></i>Wi-Fi desconectado';
      }
    }
    atualizarDados();
    setInterval(atualizarDados, 3000);
  </script>
</body>
</html>
)HTML";

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

void responderPagina() {
  servidor.send_P(200, "text/html; charset=utf-8", PAGINA_HTML);
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

  servidor.on("/", HTTP_GET, responderPagina);
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

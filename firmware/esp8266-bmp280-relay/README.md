# Controlador ESP8266 + BMP280 + rele

Firmware PlatformIO para Wemos D1 mini (ESP8266), BMP280 I2C e modulo rele.

## Ligacoes

Desligue a alimentacao antes de alterar fios. O BMP280 trabalha em 3,3 V. Nao
conecte tensao de rede sem caixa, isolacao e instalacao profissional.

| Componente | Pino | D1 mini |
|---|---|---|
| BMP280 | VCC / GND | 3V3 / G |
| BMP280 | SCL / SDA | D1 / D2 |
| Rele | IN / GND | D5 / G |
| Rele | VCC | conforme a especificacao do modulo |

O sensor e detectado em `0x76` ou `0x77`. O rele e ativo em nivel baixo e
sempre inicia desligado. Comandos `safe_preset` desligam a bomba automaticamente
apos o tempo definido por `SAFE_PUMP_DURATION_MS` (10 segundos no exemplo).

## Configurar e gravar

1. Instale PlatformIO.
2. Copie `include/device_config.example.h` para `include/device_config.h`.
3. Preencha URL, `DEVICE_ID`, token e a CA raiz HTTPS. SSID e senha não fazem
   parte desse arquivo: o provisionamento usa o portal local.
4. Execute `pio run --target upload` e depois `pio device monitor`.

Emita o token em **Gestao > Dispositivos > dispositivo > Gerar e rotacionar
credencial**. Cadastre os canais `air-temperature` (sensor, `air_temperature`,
I2C), `air-pressure` (sensor, `air_pressure`, I2C) e `pump` (atuador,
`pump_state`, D5). O firmware envia telemetria/heartbeat e busca comandos nas
rotas existentes em `/api/v1/device/`.

O BMP280 nao mede umidade. `air-humidity` exige BME280, SHT3x ou equivalente.

## Provisionamento e modo offline

Sem credenciais Wi-Fi salvas, o controlador abre o ponto de acesso
`Horta-<chip-id>` por até três minutos. O técnico conecta o celular e usa o
portal local do WiFiManager; a senha fica somente no flash do ESP8266 e nunca é
enviada ao Django. Depois de conectado, o firmware consulta
`GET /api/device/config/` e guarda a última resposta válida no LittleFS.

A agenda de irrigação armazenada continua acionando o relé D5 sem internet. O
tempo é limitado a 300 segundos por execução. Iluminação e fertilização só
podem ser automatizadas após definir e documentar o hardware/pinos desses
atuadores; nenhuma pinagem foi inventada neste firmware.

## Dispositivo independente

O controlador não se comunica com a ESP32-CAM. Ele possui Wi-Fi, identidade e
credencial próprios e continua com sensores e automação local mesmo quando a
câmera está desligada. D6 e D7 permanecem livres, sem função definida.

## Reset de Wi-Fi

Instale um botão momentâneo entre **D0/GPIO16 e GND**. Mantenha-o pressionado por
5 segundos. O ESP8266 apaga somente as próprias credenciais e reinicia no AP
`Horta-<chip-id>`. Esse reset não afeta a câmera. D0 aceita `INPUT_PULLUP` e não
é pino de boot.

## HTTPS_ROOT_CA

HTTPS é recusado quando `HTTPS_ROOT_CA` está vazio; o firmware não usa
`setInsecure()`. Em 30/09/2026, a cadeia apresentada por
`horta-inteligente.onrender.com` era `onrender.com` -> `WE1` -> `GTS Root R4`
(cross-signed) -> `GlobalSign Root CA`. O exemplo versiona o PEM da
`GlobalSign Root CA` (SHA-1 `B1BC968BD4F49D622AA89A81F2150152A41D829C`),
válida até 28/01/2028, como trust anchor do BearSSL.

A cadeia do serviço pode mudar. Antes da expiração ou ao receber um erro de
validação TLS, consulte novamente o domínio real com SNI, valide issuer,
thumbprint e datas usando uma fonte TLS confiável, e atualize o PEM da raiz.

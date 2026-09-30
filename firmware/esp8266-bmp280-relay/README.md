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
3. Preencha URL, `DEVICE_ID`, token e a CA raiz HTTPS. As constantes Wi-Fi são
   apenas fallback legado; o provisionamento normal usa o portal local.
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

## Provisionamento conjunto da câmera

Depois que o WiFiManager conecta a residência, o ESP8266 lê as credenciais que
acabou de salvar e envia uma única linha JSON à ESP32-CAM. O SSID pode aparecer
no log; a senha nunca é impressa. O controlador espera `wifi_ack` por no máximo
5 segundos. Se a câmera estiver ausente, registra timeout e segue normalmente
com sensores, irrigação e API.

UART a 9600 baud, quando o microSD da AI Thinker não for usado:

| D1 mini | ESP32-CAM | Observação |
|---|---|---|
| D7 / GPIO13 (TX) | GPIO13 (RX2) | Dados para a câmera |
| D6 / GPIO12 (RX) | GPIO14 (TX2) | ACK da câmera |
| GND | GND | Terra comum obrigatório |

D1/D2 continuam no BMP280 e D5 no relé. D6/D7 estavam livres e não são pinos
de boot do ESP8266. GPIO13/GPIO14 não pertencem à câmera AI Thinker, mas são do
microSD; por isso UART e cartão SD não podem ser usados juntos nesta montagem.

## Reset de Wi-Fi

Instale um botão momentâneo entre **D0/GPIO16 e GND**. Mantenha-o pressionado por
5 segundos. O ESP8266 envia `wifi_reset`, aguarda o ACK por até 2 segundos,
apaga as próprias credenciais e reinicia no AP `Horta-<chip-id>`. Se a câmera
não responder, o reset do controlador continua. D0 estava livre, aceita
`INPUT_PULLUP` e não é pino de boot.

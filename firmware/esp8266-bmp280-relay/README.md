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
3. Preencha Wi-Fi, URL, token e a CA raiz HTTPS.
4. Execute `pio run --target upload` e depois `pio device monitor`.

Emita o token em **Gestao > Dispositivos > dispositivo > Gerar e rotacionar
credencial**. Cadastre os canais `air-temperature` (sensor, `air_temperature`,
I2C), `air-pressure` (sensor, `air_pressure`, I2C) e `pump` (atuador,
`pump_state`, D5). O firmware envia telemetria/heartbeat e busca comandos nas
rotas existentes em `/api/v1/device/`.

O BMP280 nao mede umidade. `air-humidity` exige BME280, SHT3x ou equivalente.

#pragma once

// Copie para device_config.h e preencha localmente. Esse arquivo nao e versionado.
#define API_BASE_URL "https://seu-servico.onrender.com"
#define DEVICE_API_TOKEN "prefixo.segredo"
#define DEVICE_ID "HORTA-001-CTRL"

// CA raiz em PEM. HTTPS e recusado se este valor estiver vazio.
#define HTTPS_ROOT_CA R"EOF(
)EOF"

#define TELEMETRY_INTERVAL_MS 60000UL
#define HEARTBEAT_INTERVAL_MS 300000UL
#define COMMAND_POLL_INTERVAL_MS 5000UL
#define SAFE_PUMP_DURATION_MS 10000UL
#define CONFIG_POLL_INTERVAL_MS 300000UL

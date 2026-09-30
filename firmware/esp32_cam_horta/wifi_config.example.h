#pragma once

// Identidade pre-gravada na preparacao do kit. Mantenha a copia real fora do Git.
const char* API_BASE_URL = "https://seu-servico.onrender.com";
const char* DEVICE_ID = "00000000-0000-0000-0000-000000000000"; // UUID do Device na plataforma
const char* DEVICE_TOKEN = "EXEMPLO_TOKEN_GERADO_NA_PLATAFORMA";

// CA raiz PEM do certificado HTTPS do servidor. HTTPS e recusado se vazio.
const char* HTTPS_ROOT_CA = R"EOF(
)EOF";

constexpr unsigned long PHOTO_INTERVAL_MS = 300000UL;

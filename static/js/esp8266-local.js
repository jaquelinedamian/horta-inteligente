// Endereco local exibido no Monitor Serial do ESP8266.
// Altere somente esta constante quando o IP do dispositivo mudar.
const ESP8266_URL = "http://192.168.0.100";
const INTERVALO_ATUALIZACAO_MS = 3000;
const TEMPO_LIMITE_MS = 2500;

const painelESP8266 = document.querySelector("[data-esp8266-painel]");

if (painelESP8266) {
  const elementos = {
    temperatura: painelESP8266.querySelector("[data-esp8266-temperatura]"),
    pressao: painelESP8266.querySelector("[data-esp8266-pressao]"),
    sensor: painelESP8266.querySelector("[data-esp8266-sensor]"),
    dispositivo: painelESP8266.querySelector("[data-esp8266-status]"),
    atualizacao: painelESP8266.querySelector("[data-esp8266-atualizacao]"),
    aviso: painelESP8266.querySelector("[data-esp8266-aviso]"),
  };

  // Mantidos em memoria para que uma falha nao apague a ultima leitura valida.
  const estado = {
    temperatura: null,
    pressao: null,
    ultimaAtualizacao: null,
  };

  function definirStatus(elemento, texto, online) {
    elemento.textContent = texto;
    elemento.classList.toggle("text-success", online);
    elemento.classList.toggle("text-danger", !online);
  }

  function atualizarInterface(dados) {
    definirStatus(elementos.dispositivo, "Online", true);
    if (dados.sensor === "online") {
      estado.temperatura = dados.temperatura;
      estado.pressao = dados.pressao;
      estado.ultimaAtualizacao = new Date();
      elementos.temperatura.textContent = dados.temperatura.toFixed(1);
      elementos.pressao.textContent = dados.pressao.toFixed(1);
      definirStatus(elementos.sensor, "Online", true);
      elementos.atualizacao.textContent = estado.ultimaAtualizacao.toLocaleTimeString("pt-BR");
      elementos.aviso.classList.add("d-none");
    } else {
      definirStatus(elementos.sensor, "Offline", false);
      elementos.aviso.textContent = "O ESP8266 respondeu, mas o BMP280 está offline. Os últimos valores válidos foram mantidos.";
      elementos.aviso.classList.remove("d-none");
    }
  }

  function mostrarFalha() {
    definirStatus(elementos.sensor, "Sem comunicação", false);
    definirStatus(elementos.dispositivo, "Offline", false);
    elementos.aviso.textContent = "Sem resposta do dispositivo. Os últimos valores válidos, quando existentes, permanecem exibidos.";
    elementos.aviso.classList.remove("d-none");

    // Os valores permanecem na tela. Se ainda nao houve leitura, mostram "--".
    if (estado.ultimaAtualizacao) {
      elementos.atualizacao.textContent =
        `${estado.ultimaAtualizacao.toLocaleTimeString("pt-BR")} (desatualizado)`;
    }
  }

  function validarDados(dados) {
    if (!dados || dados.wifi !== "online" || !["online", "offline"].includes(dados.sensor))
      throw new Error("Resposta do ESP8266 incompleta");
    if (dados.sensor === "offline") return;
    const temperaturaValida = typeof dados.temperatura === "number" && Number.isFinite(dados.temperatura);
    const pressaoValida = typeof dados.pressao === "number" && Number.isFinite(dados.pressao);
    if (!temperaturaValida || !pressaoValida) throw new Error("Leitura invalida do BMP280");
  }

  async function buscarDadosESP8266() {
    const controlador = new AbortController();
    const timeout = setTimeout(() => controlador.abort(), TEMPO_LIMITE_MS);

    try {
      const resposta = await fetch(`${ESP8266_URL}/dados`, {
        cache: "no-store",
        signal: controlador.signal,
      });
      if (!resposta.ok) throw new Error(`ESP8266 respondeu HTTP ${resposta.status}`);

      const dados = await resposta.json();
      validarDados(dados);
      atualizarInterface(dados);
    } catch (erro) {
      mostrarFalha();
      console.warn("Falha ao consultar o ESP8266:", erro.message);
    } finally {
      clearTimeout(timeout);
    }
  }

  // Disponivel no console para testes manuais e futuras integracoes.
  window.buscarDadosESP8266 = buscarDadosESP8266;
  buscarDadosESP8266();
  setInterval(buscarDadosESP8266, INTERVALO_ATUALIZACAO_MS);
}

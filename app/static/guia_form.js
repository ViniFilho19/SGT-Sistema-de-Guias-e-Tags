/* Tela "Nova guia": botão "+" para novas linhas, salvamento rápido e preenchimento pelo cadastro
   ao digitar um patrimônio ou nº de série/IMEI. */
(function () {
  var tabela = document.getElementById("tabela-equipamentos");
  var botaoMais = document.getElementById("add-linha");
  if (!tabela || !botaoMais) return;

  var MAX_LINHAS = 200; // mesmo limite do schema (GuiaCreate.itens)
  var CAMPOS = ["patrimonio", "modelo", "serial", "hostname", "ip"];
  var TIPOS_SALVAVEIS = { Monitor: true, Impressora: true, Celular: true, Scanner: true };
  var timers = new WeakMap();

  var GRUPOS = { Celular: "celular", Chip: "chip" }; // demais tipos: "padrao" (mesmo mapa de web.py)

  function ajustarGrupo(linha) {
    var sel = linha.querySelector("[name=tipo_equipamento]");
    var tipo = (sel && sel.value) || "Computador";
    linha.setAttribute("data-grupo", GRUPOS[tipo] || "padrao");
    var btnSalvar = linha.querySelector("[data-acao=salvar]");
    if (btnSalvar) {
      btnSalvar.hidden = !TIPOS_SALVAVEIS[tipo];
    }
    var avSalvar = linha.querySelector(".aviso-salvar");
    if (avSalvar) avSalvar.textContent = "";
  }

  function linhas() {
    return tabela.querySelectorAll("tr.linha-eq");
  }

  function campo(linha, nome) {
    return linha.querySelector("[name=" + nome + "]");
  }

  function limparAvisos(linha) {
    linha.querySelectorAll(".sugestao, .sugestao-serial, .sugestao-imei, .aviso-salvar").forEach(function (el) {
      el.textContent = "";
    });
  }

  // ---------- botão + ----------
  botaoMais.addEventListener("click", function () {
    var todas = linhas();
    if (!todas.length || todas.length >= MAX_LINHAS) return;
    var ultima = todas[todas.length - 1];
    var nova = ultima.cloneNode(true);
    nova.querySelectorAll("input").forEach(function (i) { i.value = ""; });
    nova.querySelectorAll("select").forEach(function (s) { s.selectedIndex = 0; });
    limparAvisos(nova);
    ajustarGrupo(nova);
    ultima.parentNode.appendChild(nova);
    campo(nova, "patrimonio").focus();
    if (linhas().length >= MAX_LINHAS) botaoMais.disabled = true;
  });

  // ---------- limpar / apagar / salvar linha ----------
  function limpar(linha) {
    linha.querySelectorAll("input").forEach(function (i) { i.value = ""; });
    linha.querySelectorAll("select").forEach(function (s) { s.selectedIndex = 0; });
    limparAvisos(linha);
    ajustarGrupo(linha);
    campo(linha, "patrimonio").focus();
  }

  function apagar(linha) {
    if (linhas().length <= 1) { limpar(linha); return; } // sempre resta ao menos uma linha
    ["patrimonio", "serial", "imei"].forEach(function (n) {
      clearTimeout(timers.get(campo(linha, n)));
    });
    var vizinha = linha.nextElementSibling || linha.previousElementSibling;
    linha.remove();
    botaoMais.disabled = linhas().length >= MAX_LINHAS;
    if (vizinha && vizinha.matches("tr.linha-eq")) campo(vizinha, "patrimonio").focus();
  }

  function salvarEquipamentoLinha(linha, botao) {
    var sel = campo(linha, "tipo_equipamento");
    var tipo = (sel && sel.value) || "";
    var av = linha.querySelector(".aviso-salvar");
    if (!TIPOS_SALVAVEIS[tipo] || !av) return;

    var payload = {
      tipo: tipo,
      modelo: (campo(linha, "modelo") && campo(linha, "modelo").value) || "",
      patrimonio: (campo(linha, "patrimonio") && campo(linha, "patrimonio").value) || "",
      serial: (campo(linha, "serial") && campo(linha, "serial").value) || "",
      ip: (campo(linha, "ip") && campo(linha, "ip").value) || "",
      marca: (campo(linha, "marca") && campo(linha, "marca").value) || "",
      modelo_cel: (campo(linha, "modelo_cel") && campo(linha, "modelo_cel").value) || "",
      imei: (campo(linha, "imei") && campo(linha, "imei").value) || ""
    };

    botao.disabled = true;
    av.className = "aviso-salvar mt-1 text-xs leading-snug text-slate-500";
    av.textContent = "Salvando…";

    fetch("/equipamentos/salvar-rapido", {
      method: "POST",
      credentials: "same-origin",
      headers: { "Content-Type": "application/json", Accept: "application/json" },
      body: JSON.stringify(payload)
    })
      .then(function (r) { return r.json().then(function (d) { return { status: r.status, d: d }; }); })
      .then(function (res) {
        botao.disabled = false;
        if (res.d && res.d.ok) {
          av.className = "aviso-salvar mt-1 text-xs leading-snug font-medium text-emerald-700";
          av.textContent = res.d.criado ? "✓ Cadastrado no banco!" : "✓ Cadastro atualizado!";
          setTimeout(function () { if (av.textContent.indexOf("✓") === 0) av.textContent = ""; }, 4000);
        } else {
          av.className = "aviso-salvar mt-1 text-xs leading-snug font-medium text-red-600";
          av.textContent = (res.d && res.d.erro) || "Erro ao salvar equipamento.";
        }
      })
      .catch(function () {
        botao.disabled = false;
        av.className = "aviso-salvar mt-1 text-xs leading-snug font-medium text-red-600";
        av.textContent = "Erro de conexão ao salvar.";
      });
  }

  tabela.addEventListener("click", function (e) {
    var botao = e.target.closest("[data-acao]");
    var linha = botao && botao.closest("tr.linha-eq");
    if (!linha) return;
    var acao = botao.getAttribute("data-acao");
    if (acao === "limpar") limpar(linha);
    else if (acao === "apagar") apagar(linha);
    else if (acao === "salvar") salvarEquipamentoLinha(linha, botao);
  });

  // ---------- preenchimento pelo cadastro ----------
  function vazios(linha, d) {
    if (d.tipo === "Celular" || linha.getAttribute("data-grupo") === "celular") {
      var faltaCel = [];
      var m = campo(linha, "marca"), mc = campo(linha, "modelo_cel"), im = campo(linha, "imei");
      if (d.modelo && m && mc && !m.value.trim() && !mc.value.trim()) faltaCel.push("modelo_cel");
      if (d.serial && im && !im.value.trim()) faltaCel.push("imei");
      return faltaCel;
    }
    return CAMPOS.filter(function (nome) {
      var el = campo(linha, nome);
      return el && !el.value.trim() && d[nome];
    });
  }

  function tipoDiferente(linha, d) {
    var sel = campo(linha, "tipo_equipamento");
    if (!sel || !d.tipo || sel.value === d.tipo) return false;
    return Array.prototype.some.call(sel.options, function (o) { return o.value === d.tipo; });
  }

  function aplicarDados(linha, d) {
    var sel = campo(linha, "tipo_equipamento");
    if (tipoDiferente(linha, d)) {
      sel.value = d.tipo;
      ajustarGrupo(linha);
    }
    if (sel && sel.value === "Celular") {
      var m = campo(linha, "marca"), mc = campo(linha, "modelo_cel"), im = campo(linha, "imei");
      if (d.modelo && !m.value.trim() && !mc.value.trim()) {
        var partes = d.modelo.trim().split(/\s+/);
        if (partes.length > 1) {
          m.value = partes[0];
          mc.value = partes.slice(1).join(" ");
        } else {
          mc.value = d.modelo;
        }
      }
      if (d.serial && im && !im.value.trim()) im.value = d.serial;
    } else {
      CAMPOS.forEach(function (nome) {
        var el = campo(linha, nome);
        if (el && !el.value.trim() && d[nome]) el.value = d[nome];
      });
    }
  }

  function caixaSugestao(linha, nomeInput) {
    if (nomeInput === "imei") return linha.querySelector(".sugestao-imei") || linha.querySelector(".sugestao");
    if (nomeInput === "serial") return linha.querySelector(".sugestao-serial") || linha.querySelector(".sugestao");
    return linha.querySelector(".sugestao");
  }

  function oferecer(linha, caixa, d) {
    var falta = vazios(linha, d);
    var mudaTipo = tipoDiferente(linha, d);
    if (!falta.length && !mudaTipo) return; // nada a preencher

    var resumo = [d.tipo, d.hostname, d.modelo].filter(Boolean).join(" · ") || "equipamento cadastrado";
    var texto = document.createElement("span");
    texto.textContent = "Cadastro: " + resumo + (d.porSerial ? " (pelo nº de série)" : "");
    var botao = document.createElement("button");
    botao.type = "button";
    botao.className = "btn btn-ghost btn-sm ml-2 mt-1";
    botao.textContent = "Preencher";
    botao.addEventListener("click", function () {
      aplicarDados(linha, d);
      limparAvisos(linha);
    });
    caixa.textContent = "";
    caixa.appendChild(texto);
    caixa.appendChild(botao);
  }

  function consultar(input) {
    var linha = input.closest("tr");
    var nome = input.name; // "patrimonio", "serial" ou "imei"
    var caixa = caixaSugestao(linha, nome);
    var valor = input.value.trim();
    if (caixa) caixa.textContent = "";
    var param = nome === "patrimonio" ? "patrimonio" : "serial";
    if (!caixa || valor.length < (param === "serial" ? 3 : 2)) return;
    if (nome === "serial" && campo(linha, "patrimonio").value.trim()) return; // com patrimônio preenchido, prioriza ele
    fetch("/equipamentos/buscar?" + param + "=" + encodeURIComponent(valor), {
      credentials: "same-origin",
      headers: { Accept: "application/json" }
    })
      .then(function (r) { return r.ok ? r.json() : null; })
      .then(function (d) {
        if (d && d.encontrado && input.value.trim() === valor) {
          d.porSerial = param === "serial";
          oferecer(linha, caixa, d);
        }
      })
      .catch(function () { /* sessão expirada ou rede fora: segue sem sugestão */ });
  }

  function agendar(input, atraso) {
    clearTimeout(timers.get(input));
    timers.set(input, setTimeout(function () { consultar(input); }, atraso));
  }

  tabela.addEventListener("input", function (e) {
    if (e.target.matches("input[name=patrimonio], input[name=serial], input[name=imei]")) agendar(e.target, 350);
  });
  tabela.addEventListener("change", function (e) {
    if (e.target.matches("input[name=patrimonio], input[name=serial], input[name=imei]")) agendar(e.target, 0);
    if (e.target.matches("select[name=tipo_equipamento]")) ajustarGrupo(e.target.closest("tr"));
  });

  // linhas que já vêm preenchidas (ex.: formulário reexibido após um erro)
  linhas().forEach(function (linha) {
    ajustarGrupo(linha);
    var p = campo(linha, "patrimonio"), s = campo(linha, "serial"), im = campo(linha, "imei");
    if (p && p.value.trim()) consultar(p);
    else if (s && s.value.trim()) consultar(s);
    else if (im && im.value.trim()) consultar(im);
  });
})();

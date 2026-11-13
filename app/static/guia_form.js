/* Tela "Nova guia": botão "+" para novas linhas e preenchimento pelo cadastro ao digitar um patrimônio. */
(function () {
  var tabela = document.getElementById("tabela-equipamentos");
  var botaoMais = document.getElementById("add-linha");
  if (!tabela || !botaoMais) return;

  var MAX_LINHAS = 200; // mesmo limite do schema (GuiaCreate.itens)
  var CAMPOS = ["modelo", "serial", "hostname", "ip"];
  var timers = new WeakMap();

  function linhas() {
    return tabela.querySelectorAll("tr.linha-eq");
  }

  function campo(linha, nome) {
    return linha.querySelector("[name=" + nome + "]");
  }

  // ---------- botão + ----------
  botaoMais.addEventListener("click", function () {
    var todas = linhas();
    if (!todas.length || todas.length >= MAX_LINHAS) return;
    var ultima = todas[todas.length - 1];
    var nova = ultima.cloneNode(true);
    nova.querySelectorAll("input").forEach(function (i) { i.value = ""; });
    nova.querySelectorAll("select").forEach(function (s) { s.selectedIndex = 0; });
    var caixa = nova.querySelector(".sugestao");
    if (caixa) caixa.textContent = "";
    ultima.parentNode.appendChild(nova);
    campo(nova, "patrimonio").focus();
    if (linhas().length >= MAX_LINHAS) botaoMais.disabled = true;
  });

  // ---------- limpar / apagar linha (como numa planilha) ----------
  function limpar(linha) {
    linha.querySelectorAll("input").forEach(function (i) { i.value = ""; });
    linha.querySelectorAll("select").forEach(function (s) { s.selectedIndex = 0; });
    var caixa = linha.querySelector(".sugestao");
    if (caixa) caixa.textContent = "";
    campo(linha, "patrimonio").focus();
  }

  function apagar(linha) {
    if (linhas().length <= 1) { limpar(linha); return; } // sempre resta ao menos uma linha
    clearTimeout(timers.get(campo(linha, "patrimonio")));
    var vizinha = linha.nextElementSibling || linha.previousElementSibling;
    linha.remove();
    botaoMais.disabled = linhas().length >= MAX_LINHAS;
    if (vizinha && vizinha.matches("tr.linha-eq")) campo(vizinha, "patrimonio").focus();
  }

  tabela.addEventListener("click", function (e) {
    var botao = e.target.closest("[data-acao]");
    var linha = botao && botao.closest("tr.linha-eq");
    if (!linha) return;
    if (botao.getAttribute("data-acao") === "limpar") limpar(linha);
    else if (botao.getAttribute("data-acao") === "apagar") apagar(linha);
  });

  // ---------- preenchimento pelo cadastro ----------
  function vazios(linha, d) {
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

  function oferecer(linha, caixa, d) {
    var falta = vazios(linha, d);
    var mudaTipo = tipoDiferente(linha, d);
    if (!falta.length && !mudaTipo) return; // nada a preencher

    var resumo = [d.hostname, d.modelo].filter(Boolean).join(" · ") || "equipamento cadastrado";
    var texto = document.createElement("span");
    texto.textContent = "Cadastro: " + resumo;
    var botao = document.createElement("button");
    botao.type = "button";
    botao.className = "btn btn-ghost btn-sm ml-2 mt-1";
    botao.textContent = "Preencher lacunas";
    botao.addEventListener("click", function () {
      if (mudaTipo) campo(linha, "tipo_equipamento").value = d.tipo;
      falta.forEach(function (nome) { campo(linha, nome).value = d[nome]; });
      caixa.textContent = "";
    });
    caixa.textContent = "";
    caixa.appendChild(texto);
    caixa.appendChild(botao);
  }

  function consultar(input) {
    var linha = input.closest("tr");
    var caixa = linha.querySelector(".sugestao");
    var valor = input.value.trim();
    if (caixa) caixa.textContent = "";
    if (!caixa || valor.length < 2) return;
    fetch("/equipamentos/buscar?patrimonio=" + encodeURIComponent(valor), {
      credentials: "same-origin",
      headers: { Accept: "application/json" }
    })
      .then(function (r) { return r.ok ? r.json() : null; })
      .then(function (d) {
        // ignora respostas antigas se o campo mudou enquanto a consulta rodava
        if (d && d.encontrado && input.value.trim() === valor) oferecer(linha, caixa, d);
      })
      .catch(function () { /* sessão expirada ou rede fora: segue sem sugestão */ });
  }

  function agendar(input, atraso) {
    clearTimeout(timers.get(input));
    timers.set(input, setTimeout(function () { consultar(input); }, atraso));
  }

  tabela.addEventListener("input", function (e) {
    if (e.target.matches("input[name=patrimonio]")) agendar(e.target, 400);
  });
  tabela.addEventListener("change", function (e) {
    if (e.target.matches("input[name=patrimonio]")) agendar(e.target, 0);
  });

  // linhas que já vêm preenchidas (ex.: formulário reexibido após um erro)
  linhas().forEach(function (linha) {
    var p = campo(linha, "patrimonio");
    if (p && p.value.trim()) consultar(p);
  });
})();
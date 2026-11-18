/* Almoxarifado: campos de entrada/saída e linhas da cesta da entrada em lote. */
(function () {
  // Movimentação avulsa: mostra só os campos do tipo marcado (os escondidos ficam desligados e não são exigidos)
  document.querySelectorAll("form[data-mov]").forEach(function (form) {
    function aplicar() {
      var marcado = form.querySelector("[name=tipo]:checked");
      var tipo = marcado ? marcado.value : "entrada";
      form.querySelectorAll("[data-so]").forEach(function (el) {
        var ativo = el.getAttribute("data-so") === tipo;
        el.hidden = !ativo;
        el.querySelectorAll("input,select").forEach(function (c) { c.disabled = !ativo; });
        if (el.matches("input,select")) el.disabled = !ativo;
      });
    }
    form.addEventListener("change", function (e) { if (e.target.name === "tipo") aplicar(); });
    aplicar();

    // Saída: mostra a máquina do patrimônio digitado (confirma que a peça vai para o equipamento certo)
    var pat = form.querySelector("[name=patrimonio]"), info = form.querySelector("[data-maquina]"), timer;
    if (!pat || !info) return;
    function mostrar(texto, classe) { info.textContent = texto; info.className = "mt-1.5 text-xs leading-snug " + classe; }
    function consultar() {
      var v = pat.value.trim();
      if (v.length < 3) { mostrar("", "text-slate-500"); return; }
      fetch("/equipamentos/buscar?patrimonio=" + encodeURIComponent(v), {
        credentials: "same-origin", headers: { Accept: "application/json" }
      })
        .then(function (r) { return r.ok ? r.json() : null; })
        .then(function (d) {
          if (pat.value.trim() !== v || !d) return;
          if (d.encontrado) {
            mostrar("✓ " + [d.hostname, d.tipo, d.modelo, d.localidade].filter(Boolean).join(" · "), "font-medium text-emerald-700");
          } else {
            mostrar("Patrimônio não cadastrado: a peça fica registrada só com o número.", "text-amber-800");
          }
        })
        .catch(function () { mostrar("", "text-slate-500"); });
    }
    pat.addEventListener("input", function () { clearTimeout(timer); timer = setTimeout(consultar, 400); });
    if (pat.value.trim()) consultar();
  });

  // Entrada em lote: adicionar e remover linhas da cesta
  var cesta = document.getElementById("cesta");
  if (!cesta) return;
  function limpar(linha) {
    linha.querySelectorAll("input").forEach(function (c) { c.value = ""; });
    linha.querySelectorAll("select").forEach(function (c) { c.selectedIndex = 0; });
  }
  document.addEventListener("click", function (e) {
    if (e.target.closest("[data-mais-item]")) {
      var linhas = cesta.querySelectorAll("[data-item]");
      var nova = linhas[linhas.length - 1].cloneNode(true);
      limpar(nova);
      linhas[linhas.length - 1].after(nova);
      nova.querySelector("select").focus();
    }
    var remover = e.target.closest("[data-remover-item]");
    if (remover) {
      var linha = remover.closest("[data-item]");
      if (cesta.querySelectorAll("[data-item]").length > 1) linha.remove();
      else limpar(linha);
    }
  });
})();

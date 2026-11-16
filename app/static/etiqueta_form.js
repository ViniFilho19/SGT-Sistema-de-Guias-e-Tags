/* Tela "Etiquetas": ao digitar um patrimônio já cadastrado, preenche os demais campos com os dados do cadastro. */
(function () {
  var bloco = document.getElementById("busca-etiqueta");
  if (!bloco) return;
  var form = bloco.closest("form");
  var pat = form.querySelector("[name=patrimonio]");
  var caixa = bloco.querySelector(".sugestao");
  var CAMPOS = { hostname: "Hostname", ip: "IP", serial: "Nº de série", localidade: "Localidade",
                 mascara: "Máscara", gateway: "Gateway" };
  var timer = null;

  function campo(nome) { return form.querySelector("[name=" + nome + "]"); }

  function aviso(texto, classe) {
    caixa.textContent = "";
    var s = document.createElement("span");
    s.textContent = texto;
    if (classe) s.className = classe;
    caixa.appendChild(s);
    return caixa;
  }

  function botao(texto, acao) {
    var b = document.createElement("button");
    b.type = "button";
    b.className = "btn btn-ghost btn-sm ml-2 mt-1";
    b.textContent = texto;
    b.addEventListener("click", acao);
    caixa.appendChild(b);
  }

  function aplicar(d) {
    var preenchidos = [], diferentes = [];
    Object.keys(CAMPOS).forEach(function (n) {
      var el = campo(n);
      if (!el || !d[n]) return;
      var atual = el.value.trim();
      if (!atual) { el.value = d[n]; preenchidos.push(CAMPOS[n]); }
      else if (atual.toLowerCase() !== String(d[n]).toLowerCase()) diferentes.push(n);
    });
    var resumo = [d.hostname, d.modelo].filter(Boolean).join(" · ") || "equipamento cadastrado";
    aviso("✓ Encontrado no cadastro: " + resumo +
          (preenchidos.length ? " — preenchido: " + preenchidos.join(", ") + "." : "."),
          "font-medium text-emerald-700");
    if (diferentes.length) {
      var dif = document.createElement("span");
      dif.className = "ml-1 text-amber-800";
      dif.textContent = " Campos digitados diferentes do cadastro: " +
        diferentes.map(function (n) { return CAMPOS[n]; }).join(", ") + ".";
      caixa.appendChild(dif);
      botao("Usar dados do cadastro", function () {
        diferentes.forEach(function (n) { campo(n).value = d[n]; });
        aviso("✓ Dados do cadastro aplicados.", "font-medium text-emerald-700");
      });
    }
  }

  function consultar() {
    var valor = pat.value.trim();
    caixa.textContent = "";
    if (valor.length < 3) return;
    aviso("Procurando no cadastro…");
    fetch("/equipamentos/buscar?patrimonio=" + encodeURIComponent(valor), {
      credentials: "same-origin", headers: { Accept: "application/json" }
    })
      .then(function (r) { return r.ok ? r.json() : null; })
      .then(function (d) {
        if (pat.value.trim() !== valor) return; // o campo mudou enquanto a consulta rodava
        if (d && d.encontrado) aplicar(d);
        else aviso("Patrimônio não cadastrado: preencha os campos abaixo (o equipamento será cadastrado).");
      })
      .catch(function () { caixa.textContent = ""; });
  }

  pat.addEventListener("input", function () { clearTimeout(timer); timer = setTimeout(consultar, 450); });
  pat.addEventListener("change", function () { clearTimeout(timer); consultar(); });
})();

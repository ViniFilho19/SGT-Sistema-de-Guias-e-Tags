/* Tela "Etiquetas": ao digitar um patrimônio ou nº de série já cadastrado, OFERECE preencher os demais campos
   com os dados do cadastro (só preenche quando o usuário clica). */
(function () {
  // IP fixo / DHCP / Wi-Fi: sem IP fixo, o campo de endereço fica desligado
  document.querySelectorAll("[data-ip-modo]").forEach(function (grupo) {
    var ip = grupo.querySelector("[name=ip]");
    function sincronizar() {
      var marcado = grupo.querySelector("[name=ip_modo]:checked");
      var fixo = !marcado || marcado.value === "fixo";
      ip.disabled = !fixo;
      ip.required = fixo;
      if (!fixo) ip.value = "";
    }
    grupo.addEventListener("change", sincronizar);
    sincronizar();
  });

  var bloco = document.getElementById("busca-etiqueta");
  if (!bloco) return;
  var form = bloco.closest("form");
  var caixa = bloco.querySelector(".sugestao");
  var CAMPOS = { patrimonio: "Patrimônio", hostname: "Hostname", ip: "IP", serial: "Nº de série",
                 localidade: "Localidade", mascara: "Máscara", gateway: "Gateway" };
  var SEM_IP = { DHCP: "dhcp", WIFI: "wifi" };
  var timer = null;

  function campo(nome) { return form.querySelector("[name=" + nome + "]"); }

  function aviso(texto, classe) {
    caixa.textContent = "";
    var s = document.createElement("span");
    s.textContent = texto;
    if (classe) s.className = classe;
    caixa.appendChild(s);
  }

  function botao(texto, acao, principal) {
    var b = document.createElement("button");
    b.type = "button";
    b.className = (principal ? "btn" : "btn btn-ghost") + " btn-sm ml-2 mt-1";
    b.textContent = texto;
    b.addEventListener("click", acao);
    caixa.appendChild(b);
  }

  // valor do campo como o usuário vê ("DHCP"/"WIFI" quando a opção sem IP fixo está marcada)
  function valor(nome) {
    if (nome === "ip") {
      var m = form.querySelector("[name=ip_modo]:checked");
      if (m && m.value !== "fixo") return m.value === "dhcp" ? "DHCP" : "WIFI";
    }
    var el = campo(nome);
    return el ? el.value.trim() : "";
  }

  function escrever(nome, v) {
    if (nome === "ip" && SEM_IP[String(v).toUpperCase()]) {
      var op = form.querySelector("[name=ip_modo][value=" + SEM_IP[String(v).toUpperCase()] + "]");
      if (op) { op.checked = true; op.dispatchEvent(new Event("change", { bubbles: true })); }
      return;
    }
    if (nome === "ip") {
      var fixo = form.querySelector("[name=ip_modo][value=fixo]");
      if (fixo && !fixo.checked) { fixo.checked = true; fixo.dispatchEvent(new Event("change", { bubbles: true })); }
    }
    campo(nome).value = v;
  }

  // '34561' e '034561' são o mesmo patrimônio; maiúsculas não contam
  function comparavel(nome, v) {
    v = String(v).trim().toLowerCase();
    return nome === "patrimonio" ? v.replace(/^0+/, "") : v;
  }

  function mostrar(d, porSerial) {
    var vazios = [], diferentes = [];
    Object.keys(CAMPOS).forEach(function (n) {
      if (!campo(n) || !d[n]) return;
      var atual = valor(n);
      if (!atual) vazios.push(n);
      else if (comparavel(n, atual) !== comparavel(n, d[n])) diferentes.push(n);
    });
    var resumo = [d.hostname, d.modelo].filter(Boolean).join(" · ") || "equipamento cadastrado";
    aviso("Encontrado no cadastro" + (porSerial ? " pelo nº de série" : "") + ": " + resumo + ".",
          "font-medium text-emerald-700");
    if (!vazios.length && !diferentes.length) {
      caixa.firstChild.textContent += " Os campos já estão iguais ao cadastro.";
      return;
    }
    if (vazios.length) {
      var s = document.createElement("span");
      s.className = "ml-1";
      s.textContent = " Deseja preencher " + vazios.map(function (n) { return CAMPOS[n]; }).join(", ") + "?";
      caixa.appendChild(s);
      botao("Sim, preencher", function () {
        vazios.forEach(function (n) { escrever(n, d[n]); });
        aviso("✓ Campos preenchidos com os dados do cadastro.", "font-medium text-emerald-700");
      }, true);
    }
    if (diferentes.length) {
      var dif = document.createElement("span");
      dif.className = "ml-1 block text-amber-800";
      dif.textContent = "Digitado diferente do cadastro: " +
        diferentes.map(function (n) { return CAMPOS[n] + " (cadastro: " + d[n] + ")"; }).join(", ") + ".";
      caixa.appendChild(dif);
      botao("Usar dados do cadastro", function () {
        vazios.concat(diferentes).forEach(function (n) { escrever(n, d[n]); });
        aviso("✓ Dados do cadastro aplicados.", "font-medium text-emerald-700");
      });
    }
    botao("Não, obrigado", function () { caixa.textContent = ""; });
  }

  function consultar(nome) {
    var v = campo(nome).value.trim();
    caixa.textContent = "";
    if (v.length < (nome === "serial" ? 5 : 3)) return;
    aviso("Procurando no cadastro…");
    fetch("/equipamentos/buscar?" + nome + "=" + encodeURIComponent(v), {
      credentials: "same-origin", headers: { Accept: "application/json" }
    })
      .then(function (r) { return r.ok ? r.json() : null; })
      .then(function (d) {
        if (campo(nome).value.trim() !== v) return; // o campo mudou enquanto a consulta rodava
        if (d && d.encontrado) mostrar(d, nome === "serial");
        else if (nome === "patrimonio") aviso("Patrimônio não cadastrado: preencha os campos (o equipamento será cadastrado).");
        else caixa.textContent = "";
      })
      .catch(function () { caixa.textContent = ""; });
  }

  ["patrimonio", "serial"].forEach(function (nome) {
    var el = campo(nome);
    if (!el) return;
    el.addEventListener("input", function () { clearTimeout(timer); timer = setTimeout(function () { consultar(nome); }, 450); });
    el.addEventListener("change", function () { clearTimeout(timer); consultar(nome); });
  });
})();

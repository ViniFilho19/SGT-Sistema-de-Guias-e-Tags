/* Tela "Etiquetas" e modal "Cadastrar equipamento": ao digitar um patrimônio ou nº de série já cadastrado,
   OFERECE preencher os demais campos com os dados do cadastro. */
(function () {
  // ---------- Modal de cadastro de equipamento (aba Equipamentos) ----------
  var dlgEq = document.getElementById("dlg-equipamento");
  var btnAbrirEq = document.getElementById("btn-abrir-cadastro");
  var btnFecharEq = document.getElementById("btn-fechar-cadastro");
  var btnCancelarEq = document.getElementById("btn-cancelar-cadastro");
  var selTipoEq = document.getElementById("sel-tipo-eq");

  function ajustarCamposEquipamento() {
    if (!dlgEq || !selTipoEq) return;
    var tipo = selTipoEq.value;
    var rotuloSerial = document.getElementById("rotulo-serial");
    if (rotuloSerial) {
      rotuloSerial.textContent = tipo === "Celular" ? "Número de série / IMEI" : "Número de série";
    }
    dlgEq.querySelectorAll("[data-so-pc]").forEach(function (el) {
      el.hidden = tipo !== "Computador";
    });
    if (tipo !== "Computador") {
      var fixo = dlgEq.querySelector("[name=ip_modo][value=fixo]");
      if (fixo && !fixo.checked) {
        fixo.checked = true;
        fixo.dispatchEvent(new Event("change", { bubbles: true }));
      }
    }
    dlgEq.querySelectorAll("[data-campo-eq]").forEach(function (bloco) {
      var tipos = bloco.getAttribute("data-campo-eq").split(",");
      var visivel = tipos.indexOf(tipo) >= 0;
      bloco.hidden = !visivel;
      bloco.querySelectorAll("input, select").forEach(function (inp) {
        if (inp.name === "ip_modo") return;
        inp.disabled = !visivel;
        if (!visivel) {
          inp.required = false;
        } else if (inp.name === "mascara" || inp.name === "gateway") {
          inp.required = false;
        } else if (inp.name === "ip") {
          var marcado = dlgEq.querySelector("[name=ip_modo]:checked");
          var ehFixo = tipo !== "Computador" || !marcado || marcado.value === "fixo";
          inp.disabled = !ehFixo;
          inp.required = ehFixo;
        } else {
          inp.required = true;
        }
      });
    });
  }

  if (dlgEq && selTipoEq) {
    selTipoEq.addEventListener("change", ajustarCamposEquipamento);
    ajustarCamposEquipamento();
    if (btnAbrirEq) {
      btnAbrirEq.addEventListener("click", function () {
        dlgEq.showModal();
        ajustarCamposEquipamento();
      });
    }
    if (btnFecharEq) btnFecharEq.addEventListener("click", function () { dlgEq.close(); });
    if (btnCancelarEq) btnCancelarEq.addEventListener("click", function () { dlgEq.close(); });
    if (dlgEq.hasAttribute("data-abrir")) {
      dlgEq.showModal();
    }
  }

  // ---------- IP fixo / DHCP / Wi-Fi ----------
  document.querySelectorAll("[data-ip-modo]").forEach(function (grupo) {
    var ip = grupo.querySelector("[name=ip]");
    function sincronizar() {
      if (grupo.hidden) return;
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
  var CAMPOS = { patrimonio: "Patrimônio", modelo: "Marca/Modelo", hostname: "Hostname", ip: "IP",
                 serial: "Nº de série", localidade: "Localidade", mascara: "Máscara", gateway: "Gateway" };
  var SEM_IP = { DHCP: "dhcp", WIFI: "wifi" };
  var timer = null;

  function campo(nome) { return form.querySelector("[name=" + nome + "]"); }

  function aviso(texto, classe) {
    if (!caixa) return;
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
    return el && !el.disabled ? el.value.trim() : "";
  }

  function escrever(nome, v) {
    var el = campo(nome);
    if (!el || el.disabled) return;
    if (nome === "ip" && SEM_IP[String(v).toUpperCase()]) {
      var op = form.querySelector("[name=ip_modo][value=" + SEM_IP[String(v).toUpperCase()] + "]");
      if (op) { op.checked = true; op.dispatchEvent(new Event("change", { bubbles: true })); }
      return;
    }
    if (nome === "ip") {
      var fixo = form.querySelector("[name=ip_modo][value=fixo]");
      if (fixo && !fixo.checked) { fixo.checked = true; fixo.dispatchEvent(new Event("change", { bubbles: true })); }
    }
    el.value = v;
  }

  // '34561' e '034561' são o mesmo patrimônio; maiúsculas não contam
  function comparavel(nome, v) {
    v = String(v).trim().toLowerCase();
    return nome === "patrimonio" ? v.replace(/^0+/, "") : v;
  }

  function mostrar(d, porSerial) {
    var vazios = [], diferentes = [];
    Object.keys(CAMPOS).forEach(function (n) {
      var el = campo(n);
      if (!el || el.disabled || !d[n]) return;
      var atual = valor(n);
      if (!atual) vazios.push(n);
      else if (comparavel(n, atual) !== comparavel(n, d[n])) diferentes.push(n);
    });
    var resumo = [d.hostname, d.modelo, d.tipo].filter(Boolean).join(" · ") || "equipamento cadastrado";
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
    var el = campo(nome);
    if (!el || el.disabled || !caixa) return;
    var v = el.value.trim();
    caixa.textContent = "";
    if (v.length < (nome === "serial" ? 3 : 2)) return;
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

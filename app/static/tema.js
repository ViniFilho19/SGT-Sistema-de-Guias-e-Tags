/* Aplica o tema antes de desenhar a página (evita "piscar" claro). Escolha salva em localStorage; senão, segue o sistema. */
(function () {
  var salvo = null;
  try { salvo = localStorage.getItem("tema"); } catch (e) {}
  var escuro = salvo ? salvo === "escuro" : window.matchMedia("(prefers-color-scheme: dark)").matches;
  document.documentElement.classList.toggle("dark", escuro);
})();

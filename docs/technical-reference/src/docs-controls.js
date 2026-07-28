(() => {
  const menuButton = document.querySelector(".menu-toggle");
  const navigation = document.getElementById("documentation-navigation");

  if (!menuButton || !navigation) return;

  const syncMenuState = () => {
    const expanded = menuButton.getAttribute("aria-expanded") === "true";
    document.body.classList.toggle("docs-menu-open", expanded);
  };

  document.addEventListener("click", () => {
    requestAnimationFrame(syncMenuState);
  });

  navigation.addEventListener("click", (event) => {
    if (event.target.closest("a")) {
      document.body.classList.remove("docs-menu-open");
    }
  });

  document.addEventListener("keydown", (event) => {
    if (event.key !== "Escape" || menuButton.getAttribute("aria-expanded") !== "true") {
      return;
    }

    event.preventDefault();
    menuButton.click();
    document.body.classList.remove("docs-menu-open");
    menuButton.focus();
  });

  syncMenuState();
})();

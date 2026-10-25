(() => {
  const sidebar = document.getElementById("sidebar");
  const toggle = document.querySelector("[data-sidebar-toggle]");
  if (sidebar && toggle) {
    toggle.addEventListener("click", () => sidebar.classList.toggle("open"));
    document.addEventListener("click", (event) => {
      if (sidebar.classList.contains("open") && !sidebar.contains(event.target) && !toggle.contains(event.target)) sidebar.classList.remove("open");
    });
  }

  const currentPath = window.location.pathname.replace(/\/$/, "") || "/";
  document.querySelectorAll(".nav-link").forEach((link) => {
    const path = link.getAttribute("href").replace(/\/$/, "");
    if (path === currentPath || (path !== "/student" && path !== "/teacher" && path !== "/admin" && currentPath.startsWith(path + "/"))) {
      link.classList.add("active");
      link.setAttribute("aria-current", "page");
    }
  });

  document.querySelectorAll("[data-toast]").forEach((toast) => {
    window.setTimeout(() => {
      toast.style.opacity = "0";
      toast.style.transform = "translateY(-7px)";
      window.setTimeout(() => toast.remove(), 250);
    }, 5000);
  });

  const dialog = document.getElementById("confirm-dialog");
  const confirmDescription = document.getElementById("confirm-description");
  let pendingForm = null;
  document.querySelectorAll("form[data-confirm]").forEach((form) => {
    form.addEventListener("submit", (event) => {
      if (form.dataset.confirmed === "true") {
        delete form.dataset.confirmed;
        return;
      }
      if (!dialog || typeof dialog.showModal !== "function") {
        if (!window.confirm(form.dataset.confirm)) event.preventDefault();
        return;
      }
      event.preventDefault();
      event.stopImmediatePropagation();
      pendingForm = form;
      confirmDescription.textContent = form.dataset.confirm || "Continue with this action?";
      dialog.showModal();
    }, true);
  });
  document.querySelector("[data-dialog-cancel]")?.addEventListener("click", () => dialog.close());
  document.querySelector("[data-dialog-confirm]")?.addEventListener("click", () => {
    if (!pendingForm) return;
    const form = pendingForm;
    pendingForm = null;
    form.dataset.confirmed = "true";
    dialog.close();
    form.requestSubmit();
  });
  dialog?.addEventListener("close", () => { pendingForm = null; });

  document.querySelectorAll("[data-search-input]").forEach((input) => {
    const target = document.querySelector(input.dataset.searchInput);
    if (!target) return;
    input.addEventListener("input", () => {
      const query = input.value.trim().toLocaleLowerCase();
      target.querySelectorAll("[data-search-row]").forEach((row) => {
        row.hidden = !row.textContent.toLocaleLowerCase().includes(query);
      });
    });
  });
})();

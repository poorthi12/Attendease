(() => {
  const form = document.querySelector("[data-attendance-form]");
  if (!form) return;

  const selects = [...form.querySelectorAll("select[data-attendance-status]")];
  const counter = form.querySelector("[data-attendance-count]");
  const dateInput = form.querySelector("[data-attendance-date]");
  const initialDate = dateInput?.value || "";
  let changed = false;

  const update = () => {
    const present = selects.filter((select) => select.value === "present").length;
    const absent = selects.filter((select) => select.value === "absent").length;
    const unmarked = selects.length - present - absent;
    if (counter) counter.textContent = `${present} present · ${absent} absent · ${unmarked} not marked`;
  };

  selects.forEach((select) => select.addEventListener("change", () => {
    changed = true;
    update();
  }));

  document.querySelectorAll("[data-mark-all]").forEach((button) => {
    button.addEventListener("click", () => {
      selects.forEach((select) => { select.value = button.dataset.markAll; });
      changed = true;
      update();
    });
  });

  dateInput?.addEventListener("change", () => {
    if (changed && !window.confirm("Discard unsaved attendance changes and load this date?")) {
      dateInput.value = initialDate;
      return;
    }
    window.location.assign(`${window.location.pathname}?class_date=${encodeURIComponent(dateInput.value)}`);
  });

  form.addEventListener("submit", (event) => {
    if (!selects.some((select) => ["present", "absent"].includes(select.value))) {
      event.preventDefault();
      window.alert("Mark at least one student before saving attendance.");
      return;
    }
    const submit = form.querySelector("button[type='submit']");
    if (submit) {
      submit.disabled = true;
      submit.classList.add("is-loading");
      submit.setAttribute("aria-label", "Saving attendance");
    }
  });

  update();
})();

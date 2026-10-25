(() => {
  const form = document.querySelector("[data-attendance-form]");
  if (!form) return;
  const selects = [...form.querySelectorAll("select[data-attendance-status]")];
  const counter = document.querySelector("[data-attendance-count]");
  const update = () => {
    const present = selects.filter((select) => select.value === "present").length;
    const absent = selects.filter((select) => select.value === "absent").length;
    if (counter) counter.textContent = `${present} present · ${absent} absent`;
  };
  selects.forEach((select) => select.addEventListener("change", update));
  document.querySelectorAll("[data-mark-all]").forEach((button) => {
    button.addEventListener("click", () => {
      selects.forEach((select) => { select.value = button.dataset.markAll; });
      update();
    });
  });
  form.addEventListener("submit", (event) => {
    if (selects.some((select) => !["present", "absent"].includes(select.value))) {
      event.preventDefault();
      window.alert("Choose present or absent for each enrolled student.");
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

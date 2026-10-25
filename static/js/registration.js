document.addEventListener("DOMContentLoaded", () => {
  document.querySelectorAll("[data-subject-registration]").forEach((form) => {
    const role = form.dataset.role;
    const groups = [...form.querySelectorAll("[data-group-key], [data-group-department]")];
    const studentGroup = form.querySelector("[data-student-group-select]");
    const teacherDepartment = form.querySelector("[data-teacher-department]");

    const updateGroups = () => {
      groups.forEach((group) => {
        const visible = role === "student"
          ? group.dataset.groupKey === studentGroup?.value
          : group.dataset.groupDepartment === teacherDepartment?.value;
        group.hidden = !visible;
        if (!visible) {
          group.querySelectorAll('input[name="subject_ids"]').forEach((input) => { input.checked = false; });
        }
      });
    };

    studentGroup?.addEventListener("change", updateGroups);
    teacherDepartment?.addEventListener("change", updateGroups);
    updateGroups();
  });
});

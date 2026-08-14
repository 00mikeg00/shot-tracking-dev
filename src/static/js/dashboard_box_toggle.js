// Dashboard "Classes"/"Films" boxes: collapsible via their header button.
// Same accordion pattern as dashboard_help.js's .help-section-toggle, just
// scoped to the two bottom-of-page boxes instead of the Help modal.
document.addEventListener("DOMContentLoaded", () => {
  document.querySelectorAll(".dashboard-box-toggle").forEach((btn) => {
    btn.addEventListener("click", () => {
      const content = document.getElementById(btn.dataset.target);
      const chevron = btn.querySelector(".dashboard-box-chevron");
      if (!content) return;

      const isOpen = !content.classList.contains("hidden");
      content.classList.toggle("hidden");
      if (chevron) chevron.style.transform = isOpen ? "rotate(-90deg)" : "rotate(0deg)";
    });
  });
});

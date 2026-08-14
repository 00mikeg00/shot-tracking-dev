// Dashboard Help modal: plain open/close + accordion toggle. All content is
// static HTML in dashboard.html -- edit the placeholder steps there directly.
document.addEventListener("DOMContentLoaded", () => {
  const helpBtn = document.getElementById("dashboard-help-btn");
  const modal = document.getElementById("dashboard-help-modal");
  const closeBtn = document.getElementById("dashboard-help-close");
  if (!helpBtn || !modal) return;

  helpBtn.addEventListener("click", () => modal.classList.remove("hidden"));
  closeBtn.addEventListener("click", () => modal.classList.add("hidden"));
  modal.addEventListener("click", (e) => {
    if (e.target === modal) modal.classList.add("hidden"); // click outside the panel closes it
  });

  modal.querySelectorAll(".help-section-toggle").forEach((btn) => {
    btn.addEventListener("click", () => {
      const content = document.getElementById(btn.dataset.target);
      const chevron = btn.querySelector(".help-chevron");
      const isOpen = !content.classList.contains("hidden");
      content.classList.toggle("hidden");
      if (chevron) chevron.style.transform = isOpen ? "rotate(0deg)" : "rotate(90deg)";
    });
  });
});

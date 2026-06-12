const navToggle = document.querySelector(".nav-toggle");
const siteNav = document.querySelector(".site-nav");
const themeToggle = document.querySelector(".theme-toggle");
const root = document.documentElement;
const savedTheme = localStorage.getItem("portfolio-theme") || "dark";

function setTheme(theme) {
  root.dataset.theme = theme;

  if (!themeToggle) {
    return;
  }

  const isDark = theme === "dark";
  themeToggle.setAttribute("aria-label", isDark ? "Switch to light mode" : "Switch to dark mode");
  themeToggle.innerHTML = `<i data-lucide="${isDark ? "sun" : "moon"}"></i>`;

  if (window.lucide) {
    window.lucide.createIcons();
  }
}

setTheme(savedTheme);

if (navToggle && siteNav) {
  navToggle.addEventListener("click", () => {
    const isOpen = siteNav.classList.toggle("is-open");
    navToggle.setAttribute("aria-expanded", String(isOpen));
  });

  siteNav.addEventListener("click", (event) => {
    if (event.target instanceof HTMLAnchorElement) {
      siteNav.classList.remove("is-open");
      navToggle.setAttribute("aria-expanded", "false");
    }
  });
}

if (themeToggle) {
  themeToggle.addEventListener("click", () => {
    const nextTheme = root.dataset.theme === "dark" ? "light" : "dark";
    localStorage.setItem("portfolio-theme", nextTheme);
    setTheme(nextTheme);
  });
}

window.addEventListener("load", () => {
  if (window.lucide) {
    window.lucide.createIcons();
    setTheme(root.dataset.theme || savedTheme);
  }
});

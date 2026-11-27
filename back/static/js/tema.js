/* Resilio · tema claro/oscuro (compartido). El idioma ya no se gestiona en el navegador:
   lo decide el servidor (enlaces /idioma/<código>). Clave de localStorage: resilio-theme. */
(function () {
    function read(key, fallback) {
        try { return localStorage.getItem(key) || fallback; } catch (e) { return fallback; }
    }
    function setTheme(theme) {
        document.documentElement.setAttribute('data-theme', theme);
        try { localStorage.setItem('resilio-theme', theme); } catch (e) { /* modo privado */ }
        document.querySelectorAll('.theme-btn').forEach(function (btn) {
            btn.classList.toggle('active', btn.dataset.theme === theme);
        });
    }
    window.setTheme = setTheme; // los onclick="setTheme('dark')" del HTML usan esta global
    document.addEventListener('DOMContentLoaded', function () { setTheme(read('resilio-theme', 'dark')); });
})();

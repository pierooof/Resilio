/*
 * Resilio · motor de idioma y tema (compartido por todas las páginas).
 * Los textos viven en cada página (o en i18n-app.js para el layout) y se
 * registran con Resilio.i18n.add({ es:{...}, en:{...}, ca:{...} }).
 * Las claves de las páginas registradas después pisan a las anteriores.
 * Se mantienen las claves de localStorage: resilio-language y resilio-theme.
 */
(function () {
    var dict = { es: {}, en: {}, ca: {} };
    var hooks = [];

    function read(key, fallback) {
        try { return localStorage.getItem(key) || fallback; } catch (e) { return fallback; }
    }
    function write(key, value) {
        try { localStorage.setItem(key, value); } catch (e) { /* modo privado */ }
    }

    function add(extra) {
        Object.keys(extra).forEach(function (lang) {
            dict[lang] = Object.assign(dict[lang] || {}, extra[lang]);
        });
    }

    function t(key, lang) {
        var d = dict[lang || read('resilio-language', 'es')] || {};
        return d[key];
    }

    function apply(lang) {
        document.querySelectorAll('[data-i18n]').forEach(function (el) {
            var text = (dict[lang] || {})[el.getAttribute('data-i18n')];
            if (text) el.textContent = text;
        });
        document.documentElement.lang = lang;
        document.querySelectorAll('.language-btn').forEach(function (btn) {
            btn.classList.toggle('active', btn.dataset.lang === lang);
        });
        hooks.forEach(function (fn) { fn(lang); });
    }

    function setLanguage(lang) {
        write('resilio-language', lang);
        apply(lang);
    }

    function setTheme(theme) {
        document.documentElement.setAttribute('data-theme', theme);
        write('resilio-theme', theme);
        document.querySelectorAll('.theme-btn').forEach(function (btn) {
            btn.classList.toggle('active', btn.dataset.theme === theme);
        });
    }

    window.Resilio = window.Resilio || {};
    window.Resilio.i18n = { add: add, t: t, apply: apply, onApply: function (fn) { hooks.push(fn); } };
    // Los onclick="setLanguage('es')" y onclick="setTheme('dark')" del HTML usan estas globales.
    window.setLanguage = setLanguage;
    window.setTheme = setTheme;
    window.applyTranslations = apply;

    document.addEventListener('DOMContentLoaded', function () {
        setTheme(read('resilio-theme', 'dark'));
        apply(read('resilio-language', 'es'));
    });
})();

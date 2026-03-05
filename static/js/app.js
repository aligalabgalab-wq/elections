// static/js/app.js - Fonctions globales

document.addEventListener('DOMContentLoaded', function() {
    // Initialiser les tooltips Bootstrap
    initTooltips();
    
    // Initialiser les popovers
    initPopovers();
    
    // Gérer les alertes auto-dismiss
    initAutoDismissAlerts();
    
    // Gérer les formulaires avec confirmation
    initConfirmForms();

    // Confirmation sur boutons/liens (ex: admin suppression)
    initConfirmActions();
    
    // Gérer le thème sombre/clair
    initThemeToggle();

    // Shell SaaS (sidebar + overlay)
    initAppShell();

    // Animations d'entrée "reveal on scroll"
    initRevealOnScroll();

    // Progress bars dynamiques (data-target-width="42%")
    initAnimatedProgressBars();

    // Hero + navbar (landing page)
    initLandingHero();
});

/**
 * Shell SaaS: sidebar collapsible + overlay mobile, état mémorisé.
 */
function initAppShell() {
    if (!document.body.classList.contains('app-layout')) return;

    const toggles = document.querySelectorAll('[data-app-sidebar-toggle]');
    const overlay = document.querySelector('[data-app-overlay]');
    const sidebarLinks = document.querySelectorAll('.app-sidebar a.app-nav-link');

    // Restaurer l'état collapsed sur desktop
    try {
        const saved = localStorage.getItem('appSidebarCollapsed');
        const isDesktop = window.matchMedia('(min-width: 993px)').matches;
        const defaultCollapsedForAdmin = saved === null && document.body.classList.contains('role-admin');

        if ((saved === '1' || defaultCollapsedForAdmin) && isDesktop) {
            document.body.classList.add('app-sidebar-collapsed');
            if (defaultCollapsedForAdmin) localStorage.setItem('appSidebarCollapsed', '1');
        }
    } catch (e) {
        // ignore
    }

    function isMobile() {
        return window.matchMedia('(max-width: 992px)').matches;
    }

    function toggleSidebar() {
        if (isMobile()) {
            document.body.classList.toggle('app-sidebar-open');
            return;
        }

        document.body.classList.toggle('app-sidebar-collapsed');
        try {
            localStorage.setItem(
                'appSidebarCollapsed',
                document.body.classList.contains('app-sidebar-collapsed') ? '1' : '0'
            );
        } catch (e) {
            // ignore
        }
    }

    function closeMobileSidebar() {
        document.body.classList.remove('app-sidebar-open');
    }

    toggles.forEach(btn => btn.addEventListener('click', toggleSidebar));

    if (overlay) {
        overlay.addEventListener('click', closeMobileSidebar);
    }

    sidebarLinks.forEach(link => {
        link.addEventListener('click', () => {
            if (isMobile()) closeMobileSidebar();
        });
    });

    document.addEventListener('keydown', (e) => {
        if (e.key === 'Escape') closeMobileSidebar();
    });

    // Si on passe de mobile => desktop, on enlève l'état "open"
    window.addEventListener('resize', () => {
        if (!isMobile()) closeMobileSidebar();
    });
}

function normalizeToastType(type) {
    const t = (type || 'info').toString().toLowerCase();
    if (t === 'error') return 'danger';
    const allowed = new Set(['primary', 'secondary', 'success', 'danger', 'warning', 'info', 'dark', 'light']);
    return allowed.has(t) ? t : 'info';
}

/**
 * Révélation progressive des éléments au scroll (subtil, accessible).
 * Ajoute `.reveal--in` quand l'élément entre dans le viewport.
 */
function initRevealOnScroll() {
    const candidates = document.querySelectorAll('main .card, main .transition-hover, main .reveal');
    if (!candidates.length) return;

    const prefersReducedMotion = window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches;
    if (prefersReducedMotion || !('IntersectionObserver' in window)) {
        candidates.forEach(el => el.classList.add('reveal--in'));
        return;
    }

    // Marquer les éléments comme "reveal" sans toucher au rendu si JS est absent.
    candidates.forEach(el => el.classList.add('reveal'));

    const io = new IntersectionObserver((entries) => {
        entries.forEach(entry => {
            if (!entry.isIntersecting) return;
            entry.target.classList.add('reveal--in');
            io.unobserve(entry.target);
        });
    }, { threshold: 0.12, rootMargin: '0px 0px -10% 0px' });

    candidates.forEach(el => io.observe(el));
}

/**
 * Anime les progress bars qui déclarent une largeur cible dans `data-target-width`.
 * Exemple: `<div class="progress-bar" data-target-width="65%"></div>`.
 */
function initAnimatedProgressBars() {
    const bars = document.querySelectorAll('[data-target-width]');
    if (!bars.length) return;

    const prefersReducedMotion = window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches;
    const setWidth = (bar) => {
        const target = (bar.dataset && bar.dataset.targetWidth) ? bar.dataset.targetWidth : '0%';
        bar.style.width = target;
    };

    if (prefersReducedMotion || !('IntersectionObserver' in window)) {
        bars.forEach(setWidth);
        return;
    }

    // Démarrer à 0 pour un effet "remplissage"
    bars.forEach(bar => {
        bar.style.width = '0%';
    });

    const io = new IntersectionObserver((entries) => {
        entries.forEach(entry => {
            if (!entry.isIntersecting) return;
            setWidth(entry.target);
            io.unobserve(entry.target);
        });
    }, { threshold: 0.2 });

    bars.forEach(bar => io.observe(bar));
}

/**
 * Initialise les tooltips Bootstrap
 */
function initTooltips() {
    const tooltipTriggerList = document.querySelectorAll('[data-bs-toggle="tooltip"]');
    const tooltipList = [...tooltipTriggerList].map(tooltipTriggerEl => {
        return new bootstrap.Tooltip(tooltipTriggerEl, {
            trigger: 'hover'
        });
    });
}

/**
 * Initialise les popovers Bootstrap
 */
function initPopovers() {
    const popoverTriggerList = document.querySelectorAll('[data-bs-toggle="popover"]');
    const popoverList = [...popoverTriggerList].map(popoverTriggerEl => {
        return new bootstrap.Popover(popoverTriggerEl, {
            trigger: 'focus'
        });
    });
}

/**
 * Initialise la fermeture automatique des alertes
 */
function initAutoDismissAlerts() {
    const alerts = document.querySelectorAll('.alert:not(.alert-permanent)');
    alerts.forEach(alert => {
        setTimeout(() => {
            if (alert && alert.classList.contains('show')) {
                const bsAlert = new bootstrap.Alert(alert);
                bsAlert.close();
            }
        }, 5000); // 5 secondes
    });
}

/**
 * Initialise les formulaires avec confirmation
 */
function initConfirmForms() {
    const confirmForms = document.querySelectorAll('form[data-confirm]');
    confirmForms.forEach(form => {
        form.addEventListener('submit', function(e) {
            const message = this.dataset.confirm || 'Êtes-vous sûr de vouloir continuer ?';
            if (!confirm(message)) {
                e.preventDefault();
                return false;
            }
        });
    });
}

/**
 * Confirmation simple pour les éléments `.confirm-action`
 * - <a class="confirm-action" href="...">
 * - <button class="confirm-action" data-url="...">
 */
function initConfirmActions() {
    const elements = document.querySelectorAll('.confirm-action');
    if (!elements.length) return;

    elements.forEach(el => {
        el.addEventListener('click', function(e) {
            const url = this.dataset.url || this.getAttribute('href');
            if (!url) return;

            const message = this.dataset.message || this.dataset.confirm || 'Êtes-vous sûr de vouloir continuer ?';
            if (!confirm(message)) {
                e.preventDefault();
                return;
            }

            e.preventDefault();
            window.location.href = url;
        });
    });
}

/**
 * Initialise le toggle de thème
 */
function initThemeToggle() {
    const themeToggle = document.getElementById('themeToggle');
    if (themeToggle) {
        themeToggle.addEventListener('click', function() {
            const html = document.documentElement;
            const currentTheme = html.getAttribute('data-bs-theme');
            const newTheme = currentTheme === 'dark' ? 'light' : 'dark';
            
            html.setAttribute('data-bs-theme', newTheme);
            localStorage.setItem('theme', newTheme);
            
            // Mettre à jour l'icône
            const icon = this.querySelector('i');
            if (newTheme === 'dark') {
                icon.className = 'bi bi-sun';
                showToast('Thème sombre activé', 'info');
            } else {
                icon.className = 'bi bi-moon';
                showToast('Thème clair activé', 'info');
            }
        });
        
        // Restaurer le thème sauvegardé
        const savedTheme = localStorage.getItem('theme') || 'light';
        document.documentElement.setAttribute('data-bs-theme', savedTheme);
        
        // Mettre à jour l'icône
        const icon = themeToggle.querySelector('i');
        icon.className = savedTheme === 'dark' ? 'bi bi-sun' : 'bi bi-moon';
    }
}

/**
 * Affiche un message toast
 * @param {string} message - Le message à afficher
 * @param {string} type - Le type de toast (success, danger, warning, info)
 * @param {number} duration - Durée d'affichage en ms (défaut: 3000)
 */
function showToast(message, type = 'info', duration = 3000) {
    const toastType = normalizeToastType(type);
    const isLightToast = toastType === 'warning' || toastType === 'light';
    const textClass = isLightToast ? 'text-dark' : 'text-white';
    const closeBtnClass = isLightToast ? '' : 'btn-close-white';

    // Créer le conteneur si inexistant
    let container = document.getElementById('toast-container');
    if (!container) {
        container = document.createElement('div');
        container.id = 'toast-container';
        container.className = 'position-fixed top-0 end-0 p-3';
        container.style.zIndex = '1090';
        document.body.appendChild(container);
    }
    
    // Créer le toast
    const toastId = 'toast-' + Date.now();
    const toastHTML = `
        <div id="${toastId}" class="toast align-items-center ${textClass} bg-${toastType} border-0" role="alert">
            <div class="d-flex">
                <div class="toast-body">
                    <i class="bi ${getToastIcon(toastType)} me-2"></i>
                    ${message}
                </div>
                <button type="button" class="btn-close ${closeBtnClass} me-2 m-auto" data-bs-dismiss="toast"></button>
            </div>
        </div>
    `;
    
    container.insertAdjacentHTML('beforeend', toastHTML);
    const toastElement = document.getElementById(toastId);
    const toast = new bootstrap.Toast(toastElement, {
        delay: duration
    });
    
    toast.show();
    
    // Nettoyer après disparition
    toastElement.addEventListener('hidden.bs.toast', function() {
        this.remove();
    });
}

/**
 * Retourne l'icône appropriée pour le type de toast
 */
function getToastIcon(type) {
    switch(type) {
        case 'success': return 'bi-check-circle-fill';
        case 'danger': return 'bi-exclamation-circle-fill';
        case 'warning': return 'bi-exclamation-triangle-fill';
        case 'info': return 'bi-info-circle-fill';
        default: return 'bi-bell-fill';
    }
}

/**
 * Affiche/masque l'overlay de chargement
 * @param {boolean} show - Afficher ou masquer l'overlay
 */
function toggleLoadingOverlay(show = true) {
    let overlay = document.getElementById('loading-overlay');
    
    if (!overlay) {
        overlay = document.createElement('div');
        overlay.id = 'loading-overlay';
        overlay.className = 'position-fixed top-0 left-0 w-100 h-100 d-flex justify-content-center align-items-center';
        overlay.style.backgroundColor = 'rgba(0, 0, 0, 0.5)';
        overlay.style.zIndex = '1080';
        overlay.innerHTML = `
            <div class="spinner-border text-primary" style="width: 3rem; height: 3rem;" role="status">
                <span class="visually-hidden">Chargement...</span>
            </div>
        `;
        document.body.appendChild(overlay);
    }
    
    if (show) {
        overlay.classList.remove('d-none');
    } else {
        overlay.classList.add('d-none');
    }
}

/**
 * Formate un nombre avec séparateurs de milliers
 * @param {number} number - Le nombre à formater
 * @param {string} locale - La locale (défaut: 'fr-FR')
 */
function formatNumber(number, locale = 'fr-FR') {
    return new Intl.NumberFormat(locale).format(number);
}

/**
 * Formatte une date
 * @param {Date|string} date - La date à formater
 * @param {string} format - Le format (défaut: 'fr-FR')
 */
function formatDate(date, format = 'fr-FR') {
    const d = new Date(date);
    return d.toLocaleDateString(format, {
        year: 'numeric',
        month: 'long',
        day: 'numeric',
        hour: '2-digit',
        minute: '2-digit'
    });
}

/**
 * Valide un email
 * @param {string} email - L'email à valider
 */
function isValidEmail(email) {
    const re = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
    return re.test(email);
}

/**
 * Valide un numéro de téléphone
 * @param {string} phone - Le numéro de téléphone à valider
 */
function isValidPhone(phone) {
    const re = /^[\+]?[(]?[0-9]{3}[)]?[-\s\.]?[0-9]{3}[-\s\.]?[0-9]{4,6}$/;
    return re.test(phone);
}

/**
 * Copie du texte dans le presse-papier
 * @param {string} text - Le texte à copier
 */
function copyToClipboard(text) {
    navigator.clipboard.writeText(text)
        .then(() => showToast('Copié dans le presse-papier', 'success'))
        .catch(err => showToast('Erreur lors de la copie', 'danger'));
}

/**
 * Vérifie si l'utilisateur est sur mobile
 */
function isMobile() {
    return window.innerWidth <= 768;
}

function initLandingHero() {
    window.addEventListener('scroll', () => {
        const header = document.getElementById('main-header');
        if (!header) return;
        if (window.scrollY > 50) {
            header.classList.add('scrolled');
        } else {
            header.classList.remove('scrolled');
        }
    });

    const phrases = [
        'Simulation des elections presidentielles',
        'Participez a une election fictive',
        'Explorez les resultats en temps reel',
        'Decouvrez le processus democratique'
    ];

    const textElement = document.getElementById('animated-text');
    let currentPhrase = 0;
    let currentChar = 0;

    function typePhrase() {
        const currentText = phrases[currentPhrase];
        textElement.textContent = currentText.substring(0, currentChar);

        if (currentChar < currentText.length) {
            currentChar++;
            setTimeout(typePhrase, 80);
        } else {
            setTimeout(erasePhrase, 2000);
        }
    }

    function erasePhrase() {
        const currentText = phrases[currentPhrase];
        textElement.textContent = currentText.substring(0, currentChar);

        if (currentChar > 0) {
            currentChar--;
            setTimeout(erasePhrase, 40);
        } else {
            currentPhrase = (currentPhrase + 1) % phrases.length;
            setTimeout(typePhrase, 500);
        }
    }

    if (textElement) {
        typePhrase();
    }

    const menuIcon = document.getElementById('menu-icon');
    const navbar = document.getElementById('main-navbar');

    if (menuIcon && navbar) {
        menuIcon.addEventListener('click', () => {
            navbar.classList.toggle('open');
            const icon = menuIcon.querySelector('i');
            if (!icon) return;
            icon.classList.toggle('bx-menu');
            icon.classList.toggle('bx-x');
            icon.classList.toggle('bi-list');
            icon.classList.toggle('bi-x');
        });
    }
}

// Exporter les fonctions globales
window.showToast = showToast;
window.toggleLoadingOverlay = toggleLoadingOverlay;
window.formatNumber = formatNumber;
window.formatDate = formatDate;
window.isValidEmail = isValidEmail;
window.isValidPhone = isValidPhone;
window.copyToClipboard = copyToClipboard;
window.isMobile = isMobile;

// static/js/main.js - Scripts globaux pour toute l'application

document.addEventListener('DOMContentLoaded', function() {
    // ========== FONCTIONS UTILITAIRES GLOBALES ==========
    
    /**
     * Affiche un toast de notification
     * @param {string} message - Message à afficher
     * @param {string} type - Type de toast (success, error, warning, info)
     */
    window.showToast = function(message, type = 'info') {
        // Créer le conteneur de toasts s'il n'existe pas
        let toastContainer = document.getElementById('toast-container');
        if (!toastContainer) {
            toastContainer = document.createElement('div');
            toastContainer.id = 'toast-container';
            toastContainer.className = 'toast-container position-fixed bottom-0 end-0 p-3';
            toastContainer.style.zIndex = '1050';
            document.body.appendChild(toastContainer);
        }
        
        // Classes Bootstrap pour le type
        const typeClasses = {
            'success': 'bg-success text-white',
            'error': 'bg-danger text-white',
            'warning': 'bg-warning text-dark',
            'info': 'bg-info text-white'
        };
        
        // Créer le toast
        const toastId = 'toast-' + Date.now();
        const toastHTML = `
            <div id="${toastId}" class="toast" role="alert" aria-live="assertive" aria-atomic="true">
                <div class="toast-header ${typeClasses[type] || ''}">
                    <strong class="me-auto">Notification</strong>
                    <small class="text-white">À l'instant</small>
                    <button type="button" class="btn-close btn-close-white" data-bs-dismiss="toast"></button>
                </div>
                <div class="toast-body">
                    ${message}
                </div>
            </div>
        `;
        
        toastContainer.insertAdjacentHTML('beforeend', toastHTML);
        
        // Afficher le toast
        const toastElement = document.getElementById(toastId);
        const toast = new bootstrap.Toast(toastElement, {
            delay: 5000
        });
        toast.show();
        
        // Supprimer le toast après fermeture
        toastElement.addEventListener('hidden.bs.toast', function() {
            this.remove();
        });
    };
    
    /**
     * Confirmation avec SweetAlert2
     * @param {string} title - Titre de la confirmation
     * @param {string} text - Texte de la confirmation
     * @param {string} confirmText - Texte du bouton de confirmation
     * @returns {Promise} Promise résolue si confirmé
     */
    window.confirmAction = function(title, text, confirmText = 'Confirmer') {
        return Swal.fire({
            title: title,
            text: text,
            icon: 'warning',
            showCancelButton: true,
            confirmButtonColor: '#0066b3',
            cancelButtonColor: '#6c757d',
            confirmButtonText: confirmText,
            cancelButtonText: 'Annuler',
            customClass: {
                confirmButton: 'btn btn-primary',
                cancelButton: 'btn btn-secondary'
            }
        });
    };
    
    // ========== GESTION DES FORMULAIRES ==========
    
    // Validation personnalisée pour les formulaires
    const forms = document.querySelectorAll('.needs-validation');
    forms.forEach(form => {
        form.addEventListener('submit', function(event) {
            if (!form.checkValidity()) {
                event.preventDefault();
                event.stopPropagation();
            }
            
            form.classList.add('was-validated');
            
            // Ajouter des styles personnalisés pour les champs invalides
            const invalidFields = form.querySelectorAll(':invalid');
            invalidFields.forEach(field => {
                field.classList.add('is-invalid');
            });
        });
        
        // Réinitialiser la validation quand l'utilisateur corrige
        form.addEventListener('input', function(event) {
            const field = event.target;
            if (field.classList.contains('is-invalid')) {
                field.classList.remove('is-invalid');
                if (field.checkValidity()) {
                    field.classList.add('is-valid');
                }
            }
        });
    });
    
    // Toggle password visibility
    document.querySelectorAll('.toggle-password').forEach(button => {
        button.addEventListener('click', function() {
            const input = this.parentElement.querySelector('input');
            const icon = this.querySelector('i');
            
            if (input.type === 'password') {
                input.type = 'text';
                icon.classList.remove('ri-eye-line');
                icon.classList.add('ri-eye-off-line');
            } else {
                input.type = 'password';
                icon.classList.remove('ri-eye-off-line');
                icon.classList.add('ri-eye-line');
            }
        });
    });
    
    // ========== ANIMATIONS ET TRANSITIONS ==========
    
    // Animation d'apparition progressive
    const observerOptions = {
        root: null,
        rootMargin: '0px',
        threshold: 0.1
    };
    
    const observer = new IntersectionObserver((entries) => {
        entries.forEach(entry => {
            if (entry.isIntersecting) {
                entry.target.classList.add('animate__animated', 'animate__fadeInUp');
                entry.target.style.opacity = '1';
                entry.target.style.transform = 'translateY(0)';
            }
        });
    }, observerOptions);
    
    // Observer les éléments avec la classe 'animate-on-scroll'
    document.querySelectorAll('.animate-on-scroll').forEach(element => {
        element.style.opacity = '0';
        element.style.transform = 'translateY(20px)';
        element.style.transition = 'opacity 0.5s ease, transform 0.5s ease';
        observer.observe(element);
    });
    
    // ========== GESTION DES DATES ==========
    
    // Formatage des dates locales
    document.querySelectorAll('[data-date]').forEach(element => {
        const date = new Date(element.dataset.date);
        if (!isNaN(date.getTime())) {
            element.textContent = formatDate(date);
        }
    });
    
    /**
     * Formate une date en français
     * @param {Date} date - Date à formater
     * @returns {string} Date formatée
     */
    function formatDate(date) {
        const options = {
            weekday: 'long',
            year: 'numeric',
            month: 'long',
            day: 'numeric',
            hour: '2-digit',
            minute: '2-digit'
        };
        return date.toLocaleDateString('fr-FR', options);
    }
    
    // ========== COMPTEUR TEMPS RÉEL ==========
    
    // Mise à jour des compteurs toutes les 30 secondes
    if (document.querySelector('[data-counter]')) {
        setInterval(updateCounters, 30000);
        updateCounters();
    }
    
    function updateCounters() {
        // Simuler des mises à jour de compteurs (dans une vraie app, ce serait une requête API)
        document.querySelectorAll('[data-counter]').forEach(counter => {
            const current = parseInt(counter.textContent.replace(/\D/g, ''));
            const increment = Math.floor(Math.random() * 10) + 1;
            animateCounter(counter, current, current + increment);
        });
    }
    
    function animateCounter(element, start, end) {
        const duration = 1000;
        const steps = 60;
        const step = (end - start) / steps;
        let current = start;
        
        const timer = setInterval(() => {
            current += step;
            if ((step > 0 && current >= end) || (step < 0 && current <= end)) {
                current = end;
                clearInterval(timer);
            }
            element.textContent = Math.round(current).toLocaleString();
        }, duration / steps);
    }
    
    // ========== GESTION DES ONGLETS ==========
    
    // Sauvegarde de l'onglet actif dans localStorage
    document.querySelectorAll('[data-bs-toggle="tab"]').forEach(tab => {
        tab.addEventListener('click', function() {
            localStorage.setItem('activeTab', this.getAttribute('href'));
        });
    });
    
    // Restaurer l'onglet actif au rechargement
    const activeTab = localStorage.getItem('activeTab');
    if (activeTab) {
        const tabElement = document.querySelector(`[href="${activeTab}"]`);
        if (tabElement) {
            const tab = new bootstrap.Tab(tabElement);
            tab.show();
        }
    }
    
    // ========== LOADING STATES ==========
    
    // Gestion des états de chargement pour les boutons
    document.querySelectorAll('[data-loading]').forEach(button => {
        button.addEventListener('click', function() {
            const originalText = this.innerHTML;
            this.innerHTML = `
                <span class="spinner-border spinner-border-sm me-2" role="status" aria-hidden="true"></span>
                Chargement...
            `;
            this.disabled = true;
            
            // Restaurer le texte original après 3 secondes (simulation)
            setTimeout(() => {
                this.innerHTML = originalText;
                this.disabled = false;
            }, 3000);
        });
    });
    
    // ========== DÉTECTION DU HORS-LIGNE ==========
    
    // Afficher un message quand l'utilisateur est hors ligne
    window.addEventListener('online', () => {
        showToast('Connexion rétablie', 'success');
    });
    
    window.addEventListener('offline', () => {
        showToast('Vous êtes hors ligne. Certaines fonctionnalités peuvent être limitées.', 'warning');
    });
    
    // ========== COPY TO CLIPBOARD ==========
    
    // Copier le texte dans le presse-papier
    document.querySelectorAll('[data-copy]').forEach(button => {
        button.addEventListener('click', function() {
            const textToCopy = this.dataset.copy;
            navigator.clipboard.writeText(textToCopy).then(() => {
                showToast('Copié dans le presse-papier', 'success');
            }).catch(err => {
                console.error('Erreur lors de la copie:', err);
                showToast('Erreur lors de la copie', 'error');
            });
        });
    });
    
    // ========== INITIALISATION DES TOOLTIPS ==========
    
    // Initialiser tous les tooltips Bootstrap
    const tooltipTriggerList = [].slice.call(document.querySelectorAll('[data-bs-toggle="tooltip"]'));
    tooltipTriggerList.map(function(tooltipTriggerEl) {
        return new bootstrap.Tooltip(tooltipTriggerEl);
    });
    
    // ========== GESTION DES MODALS ==========
    
    // Sauvegarder les données des formulaires dans les modals
    document.querySelectorAll('.modal').forEach(modal => {
        modal.addEventListener('hidden.bs.modal', function() {
            const form = this.querySelector('form');
            if (form) {
                form.reset();
                form.classList.remove('was-validated');
            }
        });
    });
    
    // ========== DÉFILEMENT LISSE ==========
    
    // Défilement doux pour les ancres
    document.querySelectorAll('a[href^="#"]').forEach(anchor => {
        anchor.addEventListener('click', function(e) {
            const targetId = this.getAttribute('href');
            if (targetId === '#') return;
            
            const targetElement = document.querySelector(targetId);
            if (targetElement) {
                e.preventDefault();
                targetElement.scrollIntoView({
                    behavior: 'smooth',
                    block: 'start'
                });
            }
        });
    });
    
    // ========== RESPONSIVE TABLES ==========
    
    // Ajouter un défilement horizontal aux tables sur mobile
    document.querySelectorAll('.table-responsive').forEach(table => {
        if (window.innerWidth < 768) {
            table.style.overflowX = 'auto';
            table.style.webkitOverflowScrolling = 'touch';
        }
    });
    
    // ========== AUTO-HIDE ALERTS ==========
    
    // Cacher automatiquement les alertes après 5 secondes
    document.querySelectorAll('.alert:not(.alert-permanent)').forEach(alert => {
        setTimeout(() => {
            const bsAlert = new bootstrap.Alert(alert);
            bsAlert.close();
        }, 5000);
    });
    
    // ========== COOKIE CONSENT ==========
    
    // Gestion du consentement aux cookies
    if (!localStorage.getItem('cookieConsent')) {
        const consentHTML = `
            <div class="cookie-consent position-fixed bottom-0 start-0 end-0 bg-dark text-white p-3">
                <div class="container">
                    <div class="d-flex flex-column flex-md-row align-items-center justify-content-between">
                        <div class="mb-3 mb-md-0">
                            <p class="mb-0 small">
                                Ce site utilise des cookies pour améliorer votre expérience.
                                <a href="/privacy" class="text-white text-decoration-underline">En savoir plus</a>
                            </p>
                        </div>
                        <div class="d-flex gap-2">
                            <button class="btn btn-sm btn-outline-light" id="rejectCookies">Refuser</button>
                            <button class="btn btn-sm btn-primary" id="acceptCookies">Accepter</button>
                        </div>
                    </div>
                </div>
            </div>
        `;
        
        document.body.insertAdjacentHTML('beforeend', consentHTML);
        
        document.getElementById('acceptCookies').addEventListener('click', () => {
            localStorage.setItem('cookieConsent', 'accepted');
            document.querySelector('.cookie-consent').remove();
        });
        
        document.getElementById('rejectCookies').addEventListener('click', () => {
            localStorage.setItem('cookieConsent', 'rejected');
            document.querySelector('.cookie-consent').remove();
        });
    }
});
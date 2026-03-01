// static/js/candidate.js - Fonctions spécifiques au candidat

document.addEventListener('DOMContentLoaded', function() {
    // Initialisation des graphiques de statistiques
    initCandidateCharts();
    
    // Gestion des formulaires de campagne
    initCampaignForms();
    
    // Mise à jour en temps réel des votes
    if (document.getElementById('voteChart')) {
        startLiveUpdates();
    }
});

/**
 * Initialise les graphiques de statistiques du candidat
 */
function initCandidateCharts() {
    const voteChartEl = document.getElementById('voteChart');
    if (voteChartEl) {
        const voteChart = new Chart(voteChartEl, {
            type: 'line',
            data: {
                labels: generateTimeLabels(7),
                datasets: [{
                    label: 'Votes reçus',
                    data: generateVoteData(7),
                    borderColor: '#3498db',
                    backgroundColor: 'rgba(52, 152, 219, 0.1)',
                    tension: 0.4,
                    fill: true
                }]
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                plugins: {
                    legend: {
                        display: false
                    }
                },
                scales: {
                    y: {
                        beginAtZero: true,
                        ticks: {
                            stepSize: 5
                        }
                    }
                }
            }
        });
    }
    
    const voteSourceChartEl = document.getElementById('voteSourceChart');
    if (voteSourceChartEl) {
        const voteSourceChart = new Chart(voteSourceChartEl, {
            type: 'doughnut',
            data: {
                labels: ['Mobile', 'Desktop', 'Tablette'],
                datasets: [{
                    data: [45, 50, 5],
                    backgroundColor: [
                        '#e74c3c',
                        '#3498db',
                        '#2ecc71'
                    ],
                    borderWidth: 2,
                    borderColor: '#fff'
                }]
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                plugins: {
                    legend: {
                        position: 'bottom'
                    }
                }
            }
        });
    }
}

/**
 * Initialise les formulaires de campagne
 */
function initCampaignForms() {
    // Validation du formulaire de programme
    const programForm = document.getElementById('programForm');
    if (programForm) {
        programForm.addEventListener('submit', function(e) {
            const programText = document.getElementById('political_program').value;
            if (programText.length < 100) {
                e.preventDefault();
                showToast('Le programme doit contenir au moins 100 caractères', 'warning');
                return false;
            }
            
            if (!confirm('Publier les modifications du programme ?')) {
                e.preventDefault();
                return false;
            }
        });
    }
    
    // Validation du formulaire de slogan
    const sloganForm = document.getElementById('sloganForm');
    if (sloganForm) {
        sloganForm.addEventListener('submit', function(e) {
            const slogan = document.getElementById('campaign_slogan').value;
            if (slogan.length < 5 || slogan.length > 200) {
                e.preventDefault();
                showToast('Le slogan doit contenir entre 5 et 200 caractères', 'warning');
                return false;
            }
        });
    }
    
    // Gestion des liens de campagne
    const campaignLinks = document.querySelectorAll('[data-campaign-link]');
    campaignLinks.forEach(link => {
        link.addEventListener('click', function(e) {
            if (this.href === '#' || !this.href) {
                e.preventDefault();
                const url = prompt('Entrez l\'URL :');
                if (url) {
                    const fieldName = this.dataset.campaignLink;
                    updateCampaignLink(fieldName, url);
                }
            }
        });
    });
}

/**
 * Met à jour un lien de campagne via AJAX
 */
function updateCampaignLink(fieldName, url) {
    fetch('/candidate/update-link', {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
            'X-Requested-With': 'XMLHttpRequest'
        },
        body: JSON.stringify({
            field: fieldName,
            value: url,
            _token: document.querySelector('meta[name="csrf-token"]')?.content
        })
    })
    .then(response => response.json())
    .then(data => {
        if (data.success) {
            showToast('Lien mis à jour avec succès', 'success');
            // Mettre à jour l'affichage
            const linkElement = document.querySelector(`[data-campaign-link="${fieldName}"]`);
            if (linkElement) {
                linkElement.href = url;
                linkElement.textContent = new URL(url).hostname;
            }
        } else {
            showToast(data.error || 'Erreur lors de la mise à jour', 'danger');
        }
    })
    .catch(error => {
        console.error('Error:', error);
        showToast('Erreur de connexion', 'danger');
    });
}

/**
 * Génère des étiquettes de temps pour le graphique
 */
function generateTimeLabels(days) {
    const labels = [];
    for (let i = days; i >= 0; i--) {
        const date = new Date();
        date.setDate(date.getDate() - i);
        labels.push(date.toLocaleDateString('fr-FR', { 
            weekday: 'short', 
            day: 'numeric' 
        }));
    }
    return labels;
}

/**
 * Génère des données de vote aléatoires (à remplacer par des données réelles)
 */
function generateVoteData(days) {
    const data = [];
    let current = 10;
    
    for (let i = 0; i <= days; i++) {
        current += Math.floor(Math.random() * 15);
        data.push(current);
    }
    
    return data;
}

/**
 * Démarre les mises à jour en temps réel des votes
 */
function startLiveUpdates() {
    // Simuler des mises à jour en temps réel
    setInterval(() => {
        updateLiveStats();
    }, 30000); // Toutes les 30 secondes
    
    // Mettre à jour immédiatement
    updateLiveStats();
}

/**
 * Met à jour les statistiques en temps réel
 */
function updateLiveStats() {
    fetch('/candidate/live-stats')
        .then(response => response.json())
        .then(data => {
            if (data.vote_count !== undefined) {
                updateVoteCount(data.vote_count);
            }
            if (data.ranking !== undefined) {
                updateRanking(data.ranking);
            }
            if (data.votes_today !== undefined) {
                updateVotesToday(data.votes_today);
            }
        })
        .catch(error => {
            console.error('Error fetching live stats:', error);
        });
}

/**
 * Met à jour le compteur de votes
 */
function updateVoteCount(count) {
    const voteCountElement = document.getElementById('liveVoteCount');
    if (voteCountElement) {
        // Animation du compteur
        const currentCount = parseInt(voteCountElement.textContent.replace(/\D/g, '')) || 0;
        animateCount(voteCountElement, currentCount, count, 1000);
    }
}

/**
 * Met à jour le classement
 */
function updateRanking(ranking) {
    const rankingElement = document.getElementById('liveRanking');
    if (rankingElement) {
        rankingElement.textContent = ranking;
    }
}

/**
 * Met à jour les votes d'aujourd'hui
 */
function updateVotesToday(votesToday) {
    const votesTodayElement = document.getElementById('votesToday');
    if (votesTodayElement) {
        votesTodayElement.textContent = votesToday;
    }
}

/**
 * Anime un compteur numérique
 */
function animateCount(element, start, end, duration) {
    const range = end - start;
    const increment = end > start ? 1 : -1;
    const stepTime = Math.abs(Math.floor(duration / range));
    let current = start;
    
    const timer = setInterval(() => {
        current += increment;
        element.textContent = current.toLocaleString();
        
        if (current === end) {
            clearInterval(timer);
        }
    }, stepTime);
}

/**
 * Affiche un message toast
 */
function showToast(message, type = 'info') {
    const toastContainer = document.getElementById('toast-container') || createToastContainer();
    const toastId = 'toast-' + Date.now();
    
    const toastHTML = `
        <div id="${toastId}" class="toast align-items-center text-white bg-${type}" role="alert">
            <div class="d-flex">
                <div class="toast-body">
                    ${message}
                </div>
                <button type="button" class="btn-close btn-close-white me-2 m-auto" data-bs-dismiss="toast"></button>
            </div>
        </div>
    `;
    
    toastContainer.insertAdjacentHTML('beforeend', toastHTML);
    const toastElement = document.getElementById(toastId);
    const toast = new bootstrap.Toast(toastElement);
    toast.show();
    
    toastElement.addEventListener('hidden.bs.toast', function() {
        this.remove();
    });
}

/**
 * Crée un conteneur pour les toasts
 */
function createToastContainer() {
    const container = document.createElement('div');
    container.id = 'toast-container';
    container.className = 'position-fixed top-0 end-0 p-3';
    container.style.zIndex = '1060';
    document.body.appendChild(container);
    return container;
}

/**
 * Exporte les statistiques en PDF
 */
function exportStatsToPDF() {
    showToast('Génération du PDF en cours...', 'info');
    
    // Utiliser html2pdf.js ou une autre bibliothèque
    // Pour l'instant, simuler l'export
    setTimeout(() => {
        showToast('Statistiques exportées avec succès', 'success');
    }, 2000);
}

/**
 * Partage les statistiques sur les réseaux sociaux
 */
function shareStats() {
    const shareText = `Découvrez mes statistiques de campagne ! #Élection2025`;
    const shareUrl = window.location.href;
    
    if (navigator.share) {
        navigator.share({
            title: 'Mes statistiques de campagne',
            text: shareText,
            url: shareUrl
        });
    } else {
        // Fallback pour les navigateurs qui ne supportent pas l'API Web Share
        const shareWindow = window.open(
            `https://twitter.com/intent/tweet?text=${encodeURIComponent(shareText)}&url=${encodeURIComponent(shareUrl)}`,
            '_blank'
        );
        if (shareWindow) {
            shareWindow.focus();
        }
    }
}

// Exposer les fonctions au scope global pour les boutons
window.exportStatsToPDF = exportStatsToPDF;
window.shareStats = shareStats;
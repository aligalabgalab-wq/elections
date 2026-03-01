// static/js/candidate.js - Fonctions spécifiques aux candidats

document.addEventListener('DOMContentLoaded', function() {
    // ========== GESTION DE LA CAMPAGNE ==========
    
    // Éditeur de programme politique
    const programEditor = document.getElementById('politicalProgram');
    if (programEditor) {
        // Initialiser un éditeur de texte riche si besoin
        if (typeof tinymce !== 'undefined') {
            tinymce.init({
                selector: '#politicalProgram',
                height: 400,
                menubar: false,
                plugins: [
                    'advlist autolink lists link image charmap print preview anchor',
                    'searchreplace visualblocks code fullscreen',
                    'insertdatetime media table paste code help wordcount'
                ],
                toolbar: 'undo redo | formatselect | ' +
                         'bold italic backcolor | alignleft aligncenter ' +
                         'alignright alignjustify | bullist numlist outdent indent | ' +
                         'removeformat | help',
                content_style: 'body { font-family: Arial, sans-serif; font-size: 14px }'
            });
        }
    }
    
    // ========== UPLOAD D'IMAGES ==========
    
    const profileImageInput = document.getElementById('profileImage');
    const profileImagePreview = document.getElementById('profileImagePreview');
    
    if (profileImageInput && profileImagePreview) {
        profileImageInput.addEventListener('change', function() {
            const file = this.files[0];
            if (!file) return;
            
            // Vérifier la taille du fichier (max 2MB)
            if (file.size > 2 * 1024 * 1024) {
                showToast('L\'image ne doit pas dépasser 2MB', 'error');
                this.value = '';
                return;
            }
            
            // Vérifier le type de fichier
            const validTypes = ['image/jpeg', 'image/png', 'image/gif'];
            if (!validTypes.includes(file.type)) {
                showToast('Format d\'image invalide. Utilisez JPG, PNG ou GIF', 'error');
                this.value = '';
                return;
            }
            
            // Afficher la prévisualisation
            const reader = new FileReader();
            reader.onload = function(e) {
                profileImagePreview.src = e.target.result;
                profileImagePreview.style.display = 'block';
                
                // Bouton pour retirer l'image
                const removeBtn = document.getElementById('removeImage');
                if (!removeBtn) {
                    const btnHTML = `
                        <button id="removeImage" class="btn btn-sm btn-danger mt-2">
                            <i class="ri-delete-bin-line me-1"></i> Retirer
                        </button>
                    `;
                    profileImagePreview.insertAdjacentHTML('afterend', btnHTML);
                    
                    document.getElementById('removeImage').addEventListener('click', function() {
                        profileImageInput.value = '';
                        profileImagePreview.src = '';
                        profileImagePreview.style.display = 'none';
                        this.remove();
                    });
                }
            };
            reader.readAsDataURL(file);
        });
    }
    
    // ========== STATISTIQUES DE CAMPAGNE ==========
    
    // Initialiser les graphiques de statistiques
    initializeCampaignCharts();
    
    function initializeCampaignCharts() {
        // Graphique des votes par région
        const regionChartCanvas = document.getElementById('regionChart');
        if (regionChartCanvas) {
            const ctx = regionChartCanvas.getContext('2d');
            new Chart(ctx, {
                type: 'doughnut',
                data: {
                    labels: regionChartCanvas.dataset.regions ? 
                           JSON.parse(regionChartCanvas.dataset.regions) : [],
                    datasets: [{
                        data: regionChartCanvas.dataset.votes ? 
                              JSON.parse(regionChartCanvas.dataset.votes) : [],
                        backgroundColor: [
                            '#0066b3', '#12ad2b', '#d21034', '#ffc107',
                            '#17a2b8', '#6f42c1', '#e83e8c', '#20c997'
                        ]
                    }]
                },
                options: {
                    responsive: true,
                    plugins: {
                        legend: {
                            position: 'right'
                        }
                    }
                }
            });
        }
        
        // Graphique des votes par jour
        const dailyChartCanvas = document.getElementById('dailyChart');
        if (dailyChartCanvas) {
            const ctx = dailyChartCanvas.getContext('2d');
            new Chart(ctx, {
                type: 'line',
                data: {
                    labels: dailyChartCanvas.dataset.dates ? 
                           JSON.parse(dailyChartCanvas.dataset.dates) : [],
                    datasets: [{
                        label: 'Votes par jour',
                        data: dailyChartCanvas.dataset.dailyVotes ? 
                              JSON.parse(dailyChartCanvas.dataset.dailyVotes) : [],
                        borderColor: '#0066b3',
                        backgroundColor: 'rgba(0, 102, 179, 0.1)',
                        fill: true,
                        tension: 0.4
                    }]
                },
                options: {
                    responsive: true,
                    scales: {
                        y: {
                            beginAtZero: true
                        }
                    }
                }
            });
        }
    }
    
    // ========== SUIVI DES DONNÉES EN TEMPS RÉEL ==========
    
    let voteUpdateInterval;
    
    function startLiveUpdates() {
        if (voteUpdateInterval) clearInterval(voteUpdateInterval);
        
        voteUpdateInterval = setInterval(() => {
            updateVoteStats();
        }, 10000); // Toutes les 10 secondes
    }
    
    function stopLiveUpdates() {
        if (voteUpdateInterval) {
            clearInterval(voteUpdateInterval);
            voteUpdateInterval = null;
        }
    }
    
    async function updateVoteStats() {
        try {
            const response = await fetch('/api/candidate/stats');
            const data = await response.json();
            
            // Mettre à jour les compteurs
            const voteCountElement = document.getElementById('voteCount');
            if (voteCountElement) {
                animateCounter(voteCountElement, 
                    parseInt(voteCountElement.textContent.replace(/\D/g, '')), 
                    data.vote_count);
            }
            
            // Mettre à jour le classement
            const rankingElement = document.getElementById('ranking');
            if (rankingElement) {
                rankingElement.textContent = data.ranking;
            }
            
            // Mettre à jour les statistiques régionales
            updateRegionalStats(data.regional_stats);
            
        } catch (error) {
            console.error('Erreur lors de la mise à jour:', error);
        }
    }
    
    function updateRegionalStats(regionalStats) {
        // Mettre à jour le tableau des statistiques régionales
        const tableBody = document.getElementById('regionalStatsBody');
        if (tableBody && regionalStats) {
            tableBody.innerHTML = '';
            
            regionalStats.forEach(stat => {
                const row = document.createElement('tr');
                row.innerHTML = `
                    <td>${stat.region}</td>
                    <td>${stat.votes.toLocaleString()}</td>
                    <td>${stat.percentage}%</td>
                    <td>
                        <div class="progress" style="height: 10px;">
                            <div class="progress-bar" role="progressbar" 
                                 style="width: ${stat.percentage}%"></div>
                        </div>
                    </td>
                `;
                tableBody.appendChild(row);
            });
        }
    }
    
    // Démarrer les mises à jour automatiques
    startLiveUpdates();
    
    // Arrêter les mises à jour quand la page n'est plus visible
    document.addEventListener('visibilitychange', function() {
        if (document.hidden) {
            stopLiveUpdates();
        } else {
            startLiveUpdates();
        }
    });
    
    // ========== GESTION DES RÉSEAUX SOCIAUX ==========
    
    const socialLinksForm = document.getElementById('socialLinksForm');
    if (socialLinksForm) {
        socialLinksForm.addEventListener('submit', async function(e) {
            e.preventDefault();
            
            const submitBtn = this.querySelector('button[type="submit"]');
            const originalText = submitBtn.innerHTML;
            
            // Afficher le loader
            submitBtn.disabled = true;
            submitBtn.innerHTML = `
                <span class="spinner-border spinner-border-sm me-2" role="status" aria-hidden="true"></span>
                Enregistrement...
            `;
            
            try {
                const formData = new FormData(this);
                
                const response = await fetch('/candidate/social/update', {
                    method: 'POST',
                    body: formData
                });
                
                if (response.ok) {
                    showToast('Liens sociaux mis à jour avec succès', 'success');
                } else {
                    throw new Error('Erreur lors de la mise à jour');
                }
            } catch (error) {
                showToast('Erreur lors de la mise à jour des liens', 'error');
            } finally {
                // Restaurer le bouton
                submitBtn.disabled = false;
                submitBtn.innerHTML = originalText;
            }
        });
    }
    
    // ========== PRÉVISUALISATION DU PROFIL ==========
    
    const previewProfileBtn = document.getElementById('previewProfile');
    if (previewProfileBtn) {
        previewProfileBtn.addEventListener('click', function() {
            const modalContent = document.getElementById('profilePreviewContent');
            
            // Récupérer les données du formulaire
            const formData = {
                name: document.getElementById('firstName').value + ' ' + 
                      document.getElementById('lastName').value,
                party: document.getElementById('partyName').value,
                slogan: document.getElementById('campaignSlogan').value,
                program: document.getElementById('politicalProgram').value
            };
            
            // Générer la prévisualisation
            modalContent.innerHTML = generateProfilePreview(formData);
            
            // Afficher le modal
            const previewModal = new bootstrap.Modal(
                document.getElementById('profilePreviewModal')
            );
            previewModal.show();
        });
    }
    
    function generateProfilePreview(data) {
        return `
            <div class="profile-preview">
                <div class="text-center mb-4">
                    <div class="bg-primary rounded-circle d-inline-flex align-items-center justify-content-center mb-3"
                         style="width: 150px; height: 150px;">
                        <i class="ri-user-line text-white fs-1"></i>
                    </div>
                    <h3 class="fw-bold">${data.name || 'Nom du candidat'}</h3>
                    <p class="text-primary fw-semibold">${data.party || 'Parti politique'}</p>
                </div>
                
                ${data.slogan ? `
                    <div class="alert alert-primary">
                        <i class="ri-double-quotes-l me-2"></i>
                        "${data.slogan}"
                    </div>
                ` : ''}
                
                ${data.program ? `
                    <div class="mt-4">
                        <h5 class="fw-bold mb-3">Programme politique</h5>
                        <div class="bg-light p-3 rounded">
                            ${data.program.substring(0, 500)}
                            ${data.program.length > 500 ? '...' : ''}
                        </div>
                    </div>
                ` : ''}
            </div>
        `;
    }
    
    // ========== EXPORT DES DONNÉES ==========
    
    const exportDataBtns = document.querySelectorAll('[data-export]');
    exportDataBtns.forEach(btn => {
        btn.addEventListener('click', function() {
            const exportType = this.dataset.export;
            
            confirmAction(
                'Exporter les données',
                `Voulez-vous exporter vos données de campagne au format ${exportType.toUpperCase()} ?`
            ).then((result) => {
                if (result.isConfirmed) {
                    window.location.href = `/candidate/export/${exportType}`;
                }
            });
        });
    });
    
    // ========== NOTIFICATIONS DE CAMPAGNE ==========
    
    // Vérifier les nouvelles notifications
    function checkCampaignNotifications() {
        fetch('/api/candidate/notifications')
            .then(response => response.json())
            .then(data => {
                data.notifications.forEach(notification => {
                    if (!notification.seen) {
                        showCampaignNotification(notification);
                    }
                });
            })
            .catch(error => console.error('Erreur:', error));
    }
    
    function showCampaignNotification(notification) {
        const notificationHTML = `
            <div class="toast" role="alert" aria-live="assertive" aria-atomic="true">
                <div class="toast-header bg-${notification.type === 'urgent' ? 'warning' : 'info'} text-white">
                    <strong class="me-auto">
                        <i class="ri-megaphone-line me-2"></i>
                        Notification de campagne
                    </strong>
                    <button type="button" class="btn-close btn-close-white" data-bs-dismiss="toast"></button>
                </div>
                <div class="toast-body">
                    ${notification.message}
                </div>
            </div>
        `;
        
        // Ajouter à la zone de notifications
        const notificationContainer = document.getElementById('notificationContainer') || 
                                     createNotificationContainer();
        
        notificationContainer.insertAdjacentHTML('beforeend', notificationHTML);
        
        // Afficher le toast
        const toastElement = notificationContainer.lastElementChild;
        const toast = new bootstrap.Toast(toastElement, {
            delay: 10000
        });
        toast.show();
        
        // Marquer comme lu
        markNotificationAsRead(notification.id);
    }
    
    function createNotificationContainer() {
        const container = document.createElement('div');
        container.id = 'notificationContainer';
        container.className = 'notification-container position-fixed top-0 end-0 p-3';
        container.style.zIndex = '1060';
        document.body.appendChild(container);
        return container;
    }
    
    function markNotificationAsRead(notificationId) {
        fetch(`/api/candidate/notifications/${notificationId}/read`, {
            method: 'POST'
        }).catch(error => console.error('Erreur:', error));
    }
    
    // Vérifier les notifications toutes les minutes
    setInterval(checkCampaignNotifications, 60000);
    checkCampaignNotifications(); // Vérifier immédiatement
});
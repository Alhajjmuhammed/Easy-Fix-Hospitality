// Progressive Web App (PWA) Manager - v2.2 (Push notifications disabled) - Last updated: 2025-09-30
class PWAManager {
    constructor() {
        this.deferredPrompt = null;
        this.isInstalled = false;
        this.isStandalone = false;
        this.serviceWorker = null;
        this.init();
    }

    showInstallButton() {
        const installButton = document.getElementById('pwa-install-btn');
        if (installButton) {
            installButton.style.display = 'block';
        }
    }

    hideInstallButton() {
        const installButton = document.getElementById('pwa-install-btn');
        if (installButton) {
            installButton.style.display = 'none';
        }
    }

    showDevModeNotification() {
        // Create a temporary notification for development mode
        const notification = document.createElement('div');
        notification.innerHTML = `
            <div style="position: fixed; top: 10px; right: 10px; z-index: 10000; 
                        background: #28a745; color: white; padding: 15px; border-radius: 8px;
                        font-family: Arial, sans-serif; font-size: 14px; box-shadow: 0 4px 12px rgba(0,0,0,0.3);">
                <strong>🔧 Development Mode</strong><br>
                Service Worker & Caches Cleared<br>
                <small>Changes will now appear immediately</small>
            </div>
        `;
        document.body.appendChild(notification);
        
        // Remove notification after 4 seconds
        setTimeout(() => {
            if (notification.parentNode) {
                notification.parentNode.removeChild(notification);
            }
        }, 4000);
    }

    async clearAllCachesForced() {
        // Additional aggressive cache clearing
        try {
            // Clear browser storage
            if ('localStorage' in window) {
                localStorage.removeItem('pwa-installed');
            }
            
            // Clear session storage
            if ('sessionStorage' in window) {
                sessionStorage.clear();
            }
            
            console.log('✅ Browser storage cleared');
        } catch (error) {
            console.error('Error clearing storage:', error);
        }
    }

    init() {
        this.checkInstallationStatus();
        
        // Professional cache management for development
        const isDevelopment = window.location.hostname === 'localhost' || 
                            window.location.hostname === '127.0.0.1' ||
                            window.location.port !== '';
        
        if (isDevelopment) {
            this.clearAllCachesForced();
        }
        
        this.registerServiceWorker();
        this.setupEventListeners();
        this.setupInstallPrompt();
    }

    checkInstallationStatus() {
        // Check if app is running in standalone mode
        this.isStandalone = window.matchMedia('(display-mode: standalone)').matches ||
                           window.navigator.standalone ||
                           document.referrer.includes('android-app://');

        // Check if app is installed
        this.isInstalled = this.isStandalone || localStorage.getItem('pwa-installed') === 'true';

        console.log('PWA Status:', {
            isInstalled: this.isInstalled,
            isStandalone: this.isStandalone
        });
    }

    async registerServiceWorker() {
        // PROFESSIONAL DEV MODE: Complete service worker management
        const isDevelopment = window.location.hostname === 'localhost' || 
                            window.location.hostname === '127.0.0.1' ||
                            window.location.port !== '';

        if (isDevelopment) {
            console.log('🔧 PWA: Development mode detected - Managing service workers professionally');
            
            if ('serviceWorker' in navigator) {
                try {
                    // 1. Get all existing registrations
                    const registrations = await navigator.serviceWorker.getRegistrations();
                    console.log('🔍 Found', registrations.length, 'service worker registrations');
                    
                    // 2. Unregister ALL existing service workers
                    for (const registration of registrations) {
                        console.log('🗑️ Unregistering service worker:', registration.scope);
                        await registration.unregister();
                    }
                    
                    // 3. Clear all caches
                    if ('caches' in window) {
                        const cacheNames = await caches.keys();
                        console.log('🗑️ Clearing', cacheNames.length, 'caches');
                        
                        for (const cacheName of cacheNames) {
                            console.log('🗑️ Deleting cache:', cacheName);
                            await caches.delete(cacheName);
                        }
                    }
                    
                    // 4. Force reload to clear any cached content
                    console.log('✅ PWA: All service workers and caches cleared for development');
                    
                    // Show notification to user
                    this.showDevModeNotification();
                    
                } catch (error) {
                    console.error('❌ Error managing service workers:', error);
                }
            }
            return;
        }
        
        // PRODUCTION MODE: Normal service worker registration
        if ('serviceWorker' in navigator) {
            try {
                const registration = await navigator.serviceWorker.register('/service-worker.js', {
                    scope: '/'
                });

                console.log('Service Worker registered successfully:', registration);
                this.serviceWorker = registration;

                // Handle service worker updates
                registration.addEventListener('updatefound', () => {
                    const newWorker = registration.installing;
                    console.log('New service worker found');

                    newWorker.addEventListener('statechange', () => {
                        if (newWorker.state === 'installed' && navigator.serviceWorker.controller) {
                            this.showUpdateNotification();
                        }
                    });
                });

                // Listen for messages from service worker
                navigator.serviceWorker.addEventListener('message', (event) => {
                    this.handleServiceWorkerMessage(event);
                });

                // Handle background sync
                if ('serviceWorker' in navigator && 'sync' in window.ServiceWorkerRegistration.prototype) {
                    console.log('Background sync is supported');
                }

                // Setup push notifications (disabled until VAPID keys are configured)
                // this.setupPushNotifications(registration);

            } catch (error) {
                console.error('Service Worker registration failed:', error);
            }
        } else {
            console.log('Service Workers are not supported');
        }
    }

    setupEventListeners() {
        // Before install prompt
        window.addEventListener('beforeinstallprompt', (e) => {
            console.log('Before install prompt fired');
            e.preventDefault();
            this.deferredPrompt = e;
            this.showInstallButton();
        });

        // App installed
        window.addEventListener('appinstalled', (e) => {
            console.log('PWA was installed');
            this.isInstalled = true;
            localStorage.setItem('pwa-installed', 'true');
            this.hideInstallButton();
            this.showInstallSuccess();
        });

        // Online/offline status
        window.addEventListener('online', () => {
            console.log('App is online');
            this.showConnectionStatus('online');
            this.syncPendingOrders();
        });

        window.addEventListener('offline', () => {
            console.log('App is offline');
            this.showConnectionStatus('offline');
        });

        // Visibility change (for background sync)
        document.addEventListener('visibilitychange', () => {
            if (!document.hidden && this.serviceWorker) {
                this.checkForUpdates();
            }
        });
    }

    setupInstallPrompt() {
        // Create install button if not already installed
        if (!this.isInstalled) {
            this.createInstallButton();
        }
    }

    async promptInstall() {
        if (this.deferredPrompt) {
            this.deferredPrompt.prompt();
            const { outcome } = await this.deferredPrompt.userChoice;
            console.log(`User response to the install prompt: ${outcome}`);
            this.deferredPrompt = null;
            this.hideInstallButton();
        }
    }

    createInstallButton() {
        // Check if button already exists
        if (document.querySelector('#pwa-install-button')) return;

        const installButton = document.createElement('button');
        installButton.id = 'pwa-install-button';
        installButton.className = 'btn btn-primary pwa-install-btn';
        installButton.innerHTML = '<i class="fas fa-download"></i> Install App';
        installButton.style.display = 'none';
        installButton.addEventListener('click', () => this.installApp());

        // Add to navbar or create floating button
        const navbar = document.querySelector('.navbar .container');
        if (navbar) {
            navbar.appendChild(installButton);
        } else {
            installButton.className += ' floating-install-btn';
            installButton.style.cssText = `
                position: fixed;
                bottom: 20px;
                right: 20px;
                z-index: 1000;
                border-radius: 50px;
                padding: 10px 20px;
            `;
            document.body.appendChild(installButton);
        }
    }

    showInstallButton() {
        const installButton = document.querySelector('#pwa-install-button');
        if (installButton && !this.isInstalled) {
            installButton.style.display = 'block';
        }
    }

    hideInstallButton() {
        const installButton = document.querySelector('#pwa-install-button');
        if (installButton) {
            installButton.style.display = 'none';
        }
    }

    async installApp() {
        if (!this.deferredPrompt) {
            console.log('Install prompt not available');
            return;
        }

        try {
            this.deferredPrompt.prompt();
            const { outcome } = await this.deferredPrompt.userChoice;
            
            console.log('Install prompt outcome:', outcome);
            
            if (outcome === 'accepted') {
                this.deferredPrompt = null;
                this.hideInstallButton();
            }
        } catch (error) {
            console.error('Install failed:', error);
        }
    }

    showInstallSuccess() {
        this.showNotification({
            title: 'App Installed Successfully!',
            message: 'You can now use the Restaurant App offline and receive push notifications.',
            type: 'success'
        });
    }

    async setupPushNotifications(registration) {
        console.log('setupPushNotifications called - but immediately returning (disabled)');
        if (!('Notification' in window) || !('PushManager' in window)) {
            console.log('Push notifications not supported');
            return;
        }

        // Skip push notifications setup until VAPID keys are properly configured
        console.log('Push notifications disabled - VAPID keys not configured');
        return;

        // Commented out until VAPID keys are set up
        /*
        // Check notification permission
        let permission = Notification.permission;
        
        if (permission === 'default') {
            // Don't request permission immediately, wait for user interaction
            this.createNotificationPrompt();
        } else if (permission === 'granted') {
            await this.subscribeToPush(registration);
        }
        */
    }

    createNotificationPrompt() {
        // Completely disabled - return immediately
        return;
    }

    async subscribeToPush(registration) {
        try {
            // Skip push subscription until VAPID keys are properly configured
            console.log('Push notifications disabled - VAPID keys not configured');
            return;
            
            // Commented out until VAPID keys are set up
            /*
            const subscription = await registration.pushManager.subscribe({
                userVisibleOnly: true,
                applicationServerKey: this.urlBase64ToUint8Array(
                    'YOUR_VAPID_PUBLIC_KEY' // This should be configured in Django settings
                )
            });

            console.log('Push subscription:', subscription);

            // Send subscription to server
            await this.sendSubscriptionToServer(subscription);
            */
        } catch (error) {
            console.error('Push subscription failed:', error);
        }
    }

    async sendSubscriptionToServer(subscription) {
        try {
            const response = await fetch('/api/push-subscribe/', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'X-CSRFToken': this.getCSRFToken()
                },
                body: JSON.stringify({
                    subscription: subscription,
                    user_agent: navigator.userAgent
                }),
                credentials: 'same-origin'
            });

            if (response.ok) {
                console.log('Push subscription sent to server');
            } else {
                console.error('Failed to send push subscription to server');
            }
        } catch (error) {
            console.error('Error sending push subscription:', error);
        }
    }

    urlBase64ToUint8Array(base64String) {
        const padding = '='.repeat((4 - base64String.length % 4) % 4);
        const base64 = (base64String + padding).replace(/-/g, '+').replace(/_/g, '/');
        const rawData = window.atob(base64);
        const outputArray = new Uint8Array(rawData.length);
        
        for (let i = 0; i < rawData.length; ++i) {
            outputArray[i] = rawData.charCodeAt(i);
        }
        return outputArray;
    }

    showUpdateNotification() {
        const updateNotification = document.createElement('div');
        updateNotification.className = 'alert alert-warning alert-dismissible position-fixed';
        updateNotification.style.cssText = 'top: 70px; left: 50%; transform: translateX(-50%); z-index: 1050; max-width: 400px;';
        
        updateNotification.innerHTML = `
            <h6><i class="fas fa-sync-alt"></i> App Update Available</h6>
            <p class="mb-2">A new version of the app is ready!</p>
            <button class="btn btn-sm btn-primary" id="update-app">Update Now</button>
            <button type="button" class="btn-close" data-bs-dismiss="alert"></button>
        `;

        document.body.appendChild(updateNotification);

        document.getElementById('update-app').addEventListener('click', () => {
            this.updateApp();
            updateNotification.remove();
        });
    }

    updateApp() {
        if (this.serviceWorker && this.serviceWorker.waiting) {
            this.serviceWorker.waiting.postMessage({ type: 'SKIP_WAITING' });
            window.location.reload();
        }
    }

    async checkForUpdates() {
        if (this.serviceWorker) {
            await this.serviceWorker.update();
        }
    }

    showConnectionStatus(status) {
        const connectionStatus = document.getElementById('connectionStatus');
        if (connectionStatus) {
            connectionStatus.textContent = status === 'online' ? 'Online' : 'Offline';
            connectionStatus.className = `connection-status ${status}`;
        }

        // Show toast notification
        this.showNotification({
            title: status === 'online' ? 'Back Online' : 'Offline Mode',
            message: status === 'online' 
                ? 'Connection restored. Syncing data...' 
                : 'You can continue using the app offline.',
            type: status === 'online' ? 'success' : 'warning'
        });
    }

    async syncPendingOrders() {
        if ('serviceWorker' in navigator && 'sync' in window.ServiceWorkerRegistration.prototype) {
            try {
                await this.serviceWorker.sync.register('background-order-sync');
                console.log('Background sync registered');
            } catch (error) {
                console.error('Background sync registration failed:', error);
            }
        }
    }

    handleServiceWorkerMessage(event) {
        const { type, data } = event.data;

        switch (type) {
            case 'ORDER_SYNCED':
                this.showNotification({
                    title: 'Order Synchronized',
                    message: 'Your order has been processed successfully.',
                    type: 'success'
                });
                break;
            case 'SYNC_FAILED':
                this.showNotification({
                    title: 'Sync Failed',
                    message: 'Unable to sync your order. Will retry automatically.',
                    type: 'warning'
                });
                break;
        }
    }

    showNotification({ title, message, type = 'info' }) {
        // Create toast notification
        const toastContainer = document.querySelector('.toast-container') || this.createToastContainer();
        
        const toast = document.createElement('div');
        toast.className = `toast align-items-center border-0 bg-${type === 'success' ? 'success' : type === 'warning' ? 'warning' : 'info'} text-white`;
        toast.setAttribute('role', 'alert');
        toast.setAttribute('aria-live', 'assertive');
        toast.setAttribute('aria-atomic', 'true');
        
        toast.innerHTML = `
            <div class="d-flex">
                <div class="toast-body">
                    <strong class="pwa-toast-title"></strong><br>
                    <span class="pwa-toast-message"></span>
                </div>
                <button type="button" class="btn-close btn-close-white me-2 m-auto" 
                        data-bs-dismiss="toast" aria-label="Close"></button>
            </div>
        `;
        // title/message are set as text, never parsed as HTML
        toast.querySelector('.pwa-toast-title').textContent = title == null ? '' : String(title);
        toast.querySelector('.pwa-toast-message').textContent = message == null ? '' : String(message);
        
        toastContainer.appendChild(toast);
        
        // Initialize and show toast
        if (typeof bootstrap !== 'undefined' && bootstrap.Toast) {
            const bsToast = new bootstrap.Toast(toast, { autohide: true, delay: 5000 });
            bsToast.show();
            
            // Remove toast after it's hidden
            toast.addEventListener('hidden.bs.toast', () => {
                toast.remove();
            });
        }
    }

    createToastContainer() {
        const container = document.createElement('div');
        container.className = 'toast-container position-fixed top-0 end-0 p-3';
        container.style.zIndex = '9999';
        document.body.appendChild(container);
        return container;
    }

    getCSRFToken() {
        const cookies = document.cookie.split(';');
        for (let cookie of cookies) {
            const [name, value] = cookie.trim().split('=');
            if (name === 'csrftoken') {
                return decodeURIComponent(value);
            }
        }
        return null;
    }

    // Public methods for integration with other components
    async cacheOrderForOffline(orderData) {
        if (this.serviceWorker) {
            this.serviceWorker.active.postMessage({
                type: 'CACHE_ORDER',
                order: orderData
            });
        }
    }

    isOffline() {
        return !navigator.onLine;
    }

    canSync() {
        return 'serviceWorker' in navigator && 'sync' in window.ServiceWorkerRegistration.prototype;
    }
}

// Initialize PWA Manager
let pwaManager;

document.addEventListener('DOMContentLoaded', function() {
    pwaManager = new PWAManager();
    
    // Make available globally
    window.pwaManager = pwaManager;
});

// Export for modules
if (typeof module !== 'undefined' && module.exports) {
    module.exports = PWAManager;
}
/**
 * AoT API Request Manager
 * 
 * Centralized API request handler with caching, deduplication, and retry logic.
 * Prevents overwhelming external APIs when multiple widgets load simultaneously.
 * 
 * Usage:
 *   window.AoTAPIManager.request('/api/geo/proxy/isric?lon=126&lat=37')
 *     .then(data => console.log(data))
 *     .catch(err => console.error(err));
 */

class APIRequestManager {
    constructor(options = {}) {
        // Memory cache for API responses
        this.cache = new Map();
        
        // Track pending requests to avoid duplicates
        this.pendingRequests = new Map();
        
        // Configuration
        this.cacheTTL = options.cacheTTL || 600000; // 10 minutes default
        this.maxRetries = options.maxRetries || 3;
        this.retryDelay = options.retryDelay || 1000; // 1 second base delay
        
        console.log('[AoT API Manager] Initialized with cacheTTL:', this.cacheTTL, 'ms');
    }

    /**
     * Main request method with caching and deduplication
     * @param {string} url - API endpoint URL
     * @param {object} options - Fetch options (method, headers, body, etc.)
     * @returns {Promise} - Resolves with response data
     */
    async request(url, options = {}) {
        // Auto-stringify body if it's an object
        if (options.body && typeof options.body === 'object' && !(options.body instanceof FormData) && !(options.body instanceof Blob)) {
            options.body = JSON.stringify(options.body);
            if (!options.headers) options.headers = {};
            if (options.headers instanceof Headers) {
                if (!options.headers.has('Content-Type')) {
                    options.headers.set('Content-Type', 'application/json');
                }
            } else if (!options.headers['Content-Type']) {
                options.headers['Content-Type'] = 'application/json';
            }
        }
        
        const cacheKey = this.getCacheKey(url, options);
        
        // 1. Check cache first
        const cached = this.getFromCache(cacheKey);
        if (cached !== null) {
            console.log('[AoT API Manager] Cache hit:', url);
            return cached;
        }
        
        // 2. Check if request is already in flight
        if (this.pendingRequests.has(cacheKey)) {
            console.log('[AoT API Manager] Request already pending, waiting:', url);
            return this.pendingRequests.get(cacheKey);
        }
        
        // 3. Make new request with retry logic
        console.log('[AoT API Manager] New request:', url);
        const promise = this.fetchWithRetry(url, options);
        this.pendingRequests.set(cacheKey, promise);
        
        try {
            const result = await promise;
            
            // Cache successful results
            if (result && !result.error) {
                this.setCache(cacheKey, result);
            }
            
            return result;
        } catch (error) {
            console.error('[AoT API Manager] Request failed:', url, error);
            throw error;
        } finally {
            this.pendingRequests.delete(cacheKey);
        }
    }
    
    /**
     * Fetch with exponential backoff retry logic
     * @param {string} url - API endpoint
     * @param {object} options - Fetch options
     * @param {number} attempt - Current attempt number
     * @returns {Promise}
     */
    async fetchWithRetry(url, options, attempt = 1) {
        try {
            const response = await fetch(url, options);
            
            // Retry on server errors (5xx) if attempts remain
            if (response.status >= 500 && response.status < 600 && attempt < this.maxRetries) {
                const delay = this.retryDelay * Math.pow(2, attempt - 1); // Exponential backoff
                console.warn(`[AoT API Manager] Retry ${attempt}/${this.maxRetries} after ${delay}ms:`, url);
                await this.sleep(delay);
                return this.fetchWithRetry(url, options, attempt + 1);
            }
            
            // Check for empty response (204 No Content)
            if (response.status === 204) {
                return null;
            }
            
            // Parse JSON response
            const data = await response.json();
            
            // Handle application-level errors
            if (!response.ok) {
                console.error('[AoT API Manager] HTTP error:', response.status, data);
                return { error: data.error || `HTTP ${response.status}`, status: response.status };
            }
            
            return data;
            
        } catch (error) {
            // Retry on network errors if attempts remain
            if (attempt < this.maxRetries) {
                const delay = this.retryDelay * Math.pow(2, attempt - 1);
                console.warn(`[AoT API Manager] Network error, retry ${attempt}/${this.maxRetries} after ${delay}ms:`, error.message);
                await this.sleep(delay);
                return this.fetchWithRetry(url, options, attempt + 1);
            }
            
            // Max retries exceeded
            throw error;
        }
    }
    
    /**
     * Generate cache key from URL and options
     * @param {string} url
     * @param {object} options
     * @returns {string}
     */
    getCacheKey(url, options) {
        // Include method and body in cache key
        const method = options.method || 'GET';
        const body = options.body ? JSON.stringify(options.body) : '';
        return `${method}:${url}:${body}`;
    }
    
    /**
     * Retrieve from cache if not expired
     * @param {string} key
     * @returns {object|null}
     */
    getFromCache(key) {
        const entry = this.cache.get(key);
        if (!entry) return null;
        
        // Check TTL
        if (Date.now() - entry.timestamp > this.cacheTTL) {
            this.cache.delete(key);
            return null;
        }
        
        return entry.data;
    }
    
    /**
     * Store in cache with timestamp
     * @param {string} key
     * @param {object} data
     */
    setCache(key, data) {
        this.cache.set(key, {
            data: data,
            timestamp: Date.now()
        });
        
        // Limit cache size (prevent memory leak)
        if (this.cache.size > 100) {
            const firstKey = this.cache.keys().next().value;
            this.cache.delete(firstKey);
        }
    }
    
    /**
     * Clear all cache entries
     */
    clearCache() {
        console.log('[AoT API Manager] Cache cleared');
        this.cache.clear();
    }
    
    /**
     * Clear cache entries matching a pattern
     * @param {string|RegExp} pattern - URL pattern to match
     */
    clearCachePattern(pattern) {
        const regex = typeof pattern === 'string' ? new RegExp(pattern) : pattern;
        let cleared = 0;
        
        for (const [key, _] of this.cache) {
            if (regex.test(key)) {
                this.cache.delete(key);
                cleared++;
            }
        }
        
        console.log(`[AoT API Manager] Cleared ${cleared} cache entries matching:`, pattern);
    }
    
    /**
     * Sleep utility
     * @param {number} ms - Milliseconds to sleep
     * @returns {Promise}
     */
    sleep(ms) {
        return new Promise(resolve => setTimeout(resolve, ms));
    }
    
    /**
     * Get cache statistics
     * @returns {object}
     */
    getStats() {
        return {
            cacheSize: this.cache.size,
            pendingRequests: this.pendingRequests.size,
            cacheTTL: this.cacheTTL,
            maxRetries: this.maxRetries
        };
    }
}

// Create global singleton instance
if (!window.AoTAPIManager) {
    window.AoTAPIManager = new APIRequestManager({
        cacheTTL: 600000,  // 10 minutes
        maxRetries: 3,
        retryDelay: 1000   // 1 second base
    });
    
    console.log('[AoT API Manager] Global instance created');
}

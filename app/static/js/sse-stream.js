/**
 * SSE Stream Manager for InterviewQ
 * Supports both native EventSource (GET) and Fetch API (POST/GET) streaming.
 */

class SSEManager {
    constructor(url, options = {}) {
        this.url = url;
        this.options = {
            heartbeatTimeout: 30000,
            reconnectDelay: 5000,
            maxReconnectAttempts: 5,
            useFetch: false, // Set to true to use fetch() instead of EventSource
            fetchOptions: {}, // Options passed to fetch() when useFetch is true
            ...options
        };
        this.eventSource = null;
        this.abortController = null; // For cancelling fetch requests
        this.heartbeatTimer = null;
        this.reconnectAttempts = 0;
        this.listeners = {};
        this._isConnected = false;
    }

    connect() {
        this.disconnect(); // Ensure clean state

        if (this.options.useFetch) {
            this._connectFetch();
        } else {
            this._connectEventSource();
        }

        return this;
    }

    /**
     * Native EventSource connection (GET only)
     */
    _connectEventSource() {
        this.eventSource = new EventSource(this.url);

        this.eventSource.onopen = () => {
            this._onOpen();
        };

        this.eventSource.onerror = (error) => {
            this._onError(error);
        };

        // Setup heartbeat listener
        this.addEventListener('heartbeat', () => {
            this._resetHeartbeat();
            this._emit('heartbeat');
        });
    }

    /**
     * Fetch-based connection (Supports POST, custom headers, etc.)
     * Manually parses SSE text stream.
     */
    async _connectFetch() {
        this.abortController = new AbortController();
        const fetchOptions = {
            ...this.options.fetchOptions,
            signal: this.abortController.signal,
        };

        try {
            const response = await fetch(this.url, fetchOptions);

            if (!response.ok) {
                throw new Error(`HTTP ${response.status}: ${response.statusText}`);
            }

            this._onOpen();

            const reader = response.body.getReader();
            const decoder = new TextDecoder();
            let buffer = '';
            let currentEventType = null;

            while (true) {
                const { done, value } = await reader.read();
                if (done) break;

                buffer += decoder.decode(value, { stream: true });
                const lines = buffer.split('\n');
                // Keep incomplete last line in buffer
                buffer = lines.pop() || '';

                for (const line of lines) {
                    if (line.startsWith('event: ')) {
                        currentEventType = line.slice(7).trim();
                    } else if (line.startsWith('data: ')) {
                        const dataStr = line.slice(6);
                        let parsedData;
                        try {
                            parsedData = JSON.parse(dataStr);
                        } catch (e) {
                            parsedData = dataStr;
                        }

                        // Emit specific event type or generic 'message'
                        const eventName = currentEventType || 'message';
                        this._emit(eventName, parsedData);

                        // Reset event type after data line (per SSE spec)
                        currentEventType = null;
                    } else if (line.trim() === '') {
                        // Empty line marks end of event block, reset event type
                        currentEventType = null;
                    }
                }
            }

            // Stream ended normally
            this._emit('complete');

        } catch (err) {
            if (err.name !== 'AbortError') {
                this._onError(err);
            }
        }
    }

    _onOpen() {
        this._isConnected = true;
        this.reconnectAttempts = 0;
        this._resetHeartbeat();
        this._emit('connected');
    }

    _onError(error) {
        this._isConnected = false;
        clearTimeout(this.heartbeatTimer);
        this._emit('error', error);

        // Only auto-reconnect for persistent connections (EventSource handles its own,
        // but we wrap it; for Fetch we must handle it manually).
        // Note: EventSource has built-in reconnect, so this might double-fire for ES.
        // We'll let ES handle its own reconnect and only manually reconnect for Fetch.
        if (this.options.useFetch) {
            this._handleReconnect();
        }
    }

    addEventListener(event, callback) {
        if (!this.listeners[event]) {
            this.listeners[event] = [];
        }
        this.listeners[event].push(callback);

        // For EventSource, also attach native listener if connected
        if (this.eventSource && !this.options.useFetch) {
            this.eventSource.addEventListener(event, (e) => {
                try {
                    const data = JSON.parse(e.data);
                    callback(data);
                } catch (err) {
                    callback(e.data);
                }
            });
        }

        return this;
    }

    _emit(event, data) {
        if (this.listeners[event]) {
            this.listeners[event].forEach(cb => cb(data));
        }
    }

    _resetHeartbeat() {
        clearTimeout(this.heartbeatTimer);
        if (this.options.heartbeatTimeout > 0) {
            this.heartbeatTimer = setTimeout(() => {
                console.warn('SSE heartbeat timeout, reconnecting...');
                this.reconnect();
            }, this.options.heartbeatTimeout);
        }
    }

    _handleReconnect() {
        if (this.reconnectAttempts >= this.options.maxReconnectAttempts) {
            console.error('Max reconnection attempts reached');
            this._emit('maxRetriesReached');
            return;
        }

        this.reconnectAttempts++;
        console.warn(`Reconnecting in ${this.options.reconnectDelay}ms (attempt ${this.reconnectAttempts})`);

        setTimeout(() => this.reconnect(), this.options.reconnectDelay);
    }

    reconnect() {
        this.disconnect();
        this.connect();
    }

    disconnect() {
        clearTimeout(this.heartbeatTimer);
        this._isConnected = false;

        if (this.abortController) {
            this.abortController.abort();
            this.abortController = null;
        }

        if (this.eventSource) {
            this.eventSource.close();
            this.eventSource = null;
        }
    }
}

// Export for use
window.SSEManager = SSEManager;

/**
 * General helper utilities for the Micdrop frontend.
 */

/**
 * Formats a role string into a display label.
 * @param {string} role - 'user' | 'assistant'
 * @returns {string}
 */
export function getRoleLabel(role) {
    return role === 'user' ? '👤 You' : '🤖 AI'
}

/**
 * Formats a Date object into a short time string (e.g. 12:34 PM).
 * @param {Date} date
 * @returns {string}
 */
export function formatTime(date) {
    return date.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
}

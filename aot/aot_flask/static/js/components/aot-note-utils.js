
/**
 * aot-note-utils.js
 * 
 * Handles universal note truncation behavior (400px limit, "Read More" button)
 * for both static page loads and dynamic content (modals, React widgets).
 */

(function() {
    // Configuration
    const TRUNCATION_HEIGHT = 400;

    /**
     * Initializes truncation controls for a container.
     * Can be called on the document body or specific containers like modals.
     * @param {jQuery|HTMLElement} container - The container to search within.
     */
    function initExpansionControls(container) {
        const $container = $(container);
        
        $container.find('.note-truncate-wrapper').each(function() {
            var $wrapper = $(this);
            // Verify if already initialized to check for double-binding, 
            // though logic should be idempotent.
            
            var uid = $wrapper.attr('id').replace('wrapper-', '');
            var $overlay = $wrapper.find('.note-expand-overlay');
            var $btnContainer = $('#ctrl-' + uid);

            function checkOverflow() {
                var $gallery = $wrapper.find('.note-gallery-container');
                var hasMultipleImages = false;
                try {
                    // Check logic depending on how gallery data is stored
                    // In notes.html it's data-media
                    var media = $gallery.data('media');
                    if (Array.isArray(media) && media.length > 1) {
                        hasMultipleImages = true;
                    } 
                    // Fallback: check DOM elements if data attribute isn't helpful
                    // or if logic differs in other contexts
                    else if ($wrapper.find('.note-thumbnails .thumb-item').length > 1) {
                        hasMultipleImages = true;
                    }
                } catch(e) {}

                // Logic: Show "Read More" if content is too tall OR there are multiple images
                // Using a small buffer (10px) to prevent buttons on borderline cases
                if ($wrapper[0].scrollHeight > (TRUNCATION_HEIGHT + 10) || hasMultipleImages) {
                    $overlay.show();
                    $btnContainer.show();
                } else {
                    $overlay.hide();
                    $btnContainer.hide();
                    // Ensure full visibility if small enough
                    $wrapper.css('max-height', 'none'); 
                }
                
                // FORCE: if not expanded, ensure max-height is imposed
                if (!$wrapper.hasClass('expanded') && ($wrapper[0].scrollHeight > (TRUNCATION_HEIGHT + 10) || hasMultipleImages)) {
                     $wrapper.css('max-height', TRUNCATION_HEIGHT + 'px');
                }
            }

            // Initial check
            checkOverflow();

            // Image load handling (native + standard)
            $wrapper.find('img').each(function() {
                if (this.complete) {
                    checkOverflow();
                } else {
                    $(this).on('load', function() {
                        checkOverflow();
                    });
                }
            });

            // --- INTERACTIVITY: Bind Main Image Click for Inline Expansion ---
            var $gallery = $wrapper.find('.note-gallery-container');
            // Logic to determine if multiple images based on data or DOM
            var hasMultipleImages = false;
            try {
                var media = $gallery.data('media');
                if (Array.isArray(media) && media.length > 1) {
                    hasMultipleImages = true;
                } else if ($wrapper.find('.note-thumbnails .thumb-item').length > 1) {
                    hasMultipleImages = true;
                }
            } catch(e) {}

            if (hasMultipleImages) {
                // Remove existing click handlers (e.g., from generic generic lightboxes)
                // or preventing default if we want inline expansion
                // We'll target the main image container link usually (div.main-img-link)
                var $mainImgLink = $gallery.find('.main-img-link');
                
                // Unbind previous possible handlers to avoid conflicts if re-initialized
                $mainImgLink.off('click.aotTruncate').on('click.aotTruncate', function(e) {
                    if (!$wrapper.hasClass('expanded')) {
                        e.preventDefault();
                        e.stopPropagation();
                        // Trigger expansion
                        // We simulate clicking the expand button so logic is unified
                         window.toggleNoteExpansion(uid, $btnContainer.find('.expand-toggle-btn')[0]);
                    }
                    // If already expanded, let it behave normally (e.g. open lightbox or do nothing)
                });
                
                // Also update cursor to indicate action
                $mainImgLink.css('cursor', 'pointer');
            }
            
            // Polling for robust handling of dynamic layouts (masonry, flex shifts)
            setTimeout(checkOverflow, 500);
            setTimeout(checkOverflow, 1500);
        });
    }

    /**
     * Toggles the expansion state of a note card.
     * @param {string} uid - Unique ID of the note.
     * @param {HTMLElement} btn - The button element triggered.
     */
    window.toggleNoteExpansion = function(uid, btn) {
        var $wrapper = $('#wrapper-' + uid);
        var $overlay = $('#overlay-' + uid);
        var $btnIcon = $(btn).find('i');
        var $btnText = $(btn).find('span');
        var $galleryThumbs = $wrapper.find('.note-thumbnails-wrapper');

        if ($wrapper.hasClass('expanded')) {
            // FOLD
            $wrapper.animate({
                'max-height': '400px'
            }, 300, function() {
                $wrapper.removeClass('expanded');
                $overlay.fadeIn();
                $btnIcon.removeClass('fa-chevron-up').addClass('fa-chevron-down');
                $btnText.text('Read More');
                // Hide thumbnails
                $galleryThumbs.addClass('d-none');
            });
        } else {
            // EXPAND
            var fullHeight = $wrapper[0].scrollHeight;
            $wrapper.animate({
                'max-height': fullHeight + 'px'
            }, 300, function() {
                // Remove max-height after animation to allow dynamic content resizing
                $wrapper.css('max-height', 'none');
                $wrapper.addClass('expanded');
                $overlay.fadeOut();
                $btnIcon.removeClass('fa-chevron-down').addClass('fa-chevron-up');
                $btnText.text('Show Less');
                // Show thumbnails
                $galleryThumbs.removeClass('d-none');
            });
        }
    };
    
    // Expose init function globally
    window.initNoteTruncation = initExpansionControls;

    // --- Auto-Initialization Logic ---

    // 1. On Document Ready
    $(document).ready(function() {
        initExpansionControls(document.body);
    });

    // 2. MutationObserver for Dynamic Content (React widgets, Modals)
    const observer = new MutationObserver(function(mutations) {
        let shouldCheck = false;
        mutations.forEach(function(mutation) {
            if (mutation.addedNodes.length) {
                // Optimization: Only check if relevant classes are added
                // Checking for entire subtree additions which usually happens with React/Modals
                shouldCheck = true; 
            }
        });

        if (shouldCheck) {
            // Debounce slightly to allow rendering to settle
            // Checking body is simplest; performance impact is usually negligible for this specific selector search
            initExpansionControls(document.body);
        }
    });

    observer.observe(document.body, {
        childList: true,
        subtree: true
    });
    
    // 3. Listen for specific custom events (e.g., from generic modals)
    document.addEventListener('aot-modal-shown', function(e) {
        initExpansionControls(e.target || document.body);
    });

})();

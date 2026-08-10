(function () {
    "use strict";

    let glossaryTerms = [];

    function escapeHtml(value) {
        return value
            .replace(/&/g, "&amp;")
            .replace(/</g, "&lt;")
            .replace(/>/g, "&gt;")
            .replace(/"/g, "&quot;")
            .replace(/'/g, "&#039;");
    }

    function getCurrentToken(input) {
        const cursor = input.selectionStart;
        const textBeforeCursor = input.value.slice(0, cursor);

        /*
         * Extract the text currently being typed.
         *
         * Example:
         *
         * biodiversity AND env
         *
         * current token = "env"
         */
        const match = textBeforeCursor.match(/([^\s()]+)$/);

        if (!match) {
            return {
                token: "",
                start: cursor,
                end: cursor
            };
        }

        return {
            token: match[1],
            start: cursor - match[1].length,
            end: cursor
        };
    }

    function closeSuggestions() {
        const container =
            document.getElementById("glossary-autocomplete");

        if (!container) {
            return;
        }

        container.innerHTML = "";
        container.style.display = "none";
    }

    function showSuggestions(input) {
        const container =
            document.getElementById("glossary-autocomplete");

        if (!container) {
            return;
        }

        const current = getCurrentToken(input);
        const token = current.token.trim();

        if (!token) {
            closeSuggestions();
            return;
        }

        const lowerToken = token.toLowerCase();

        const matches = glossaryTerms
            .filter(term =>
                term.toLowerCase().startsWith(lowerToken)
            )
            .slice(0, 10);

        if (matches.length === 0) {
            closeSuggestions();
            return;
        }

        container.innerHTML = "";

        matches.forEach(term => {
            const item = document.createElement("div");

            item.className = "glossary-autocomplete-item";
            item.textContent = term;

            item.addEventListener("mousedown", function (event) {
                /*
                 * Prevent the input from losing focus before
                 * we insert the selected glossary term.
                 */
                event.preventDefault();

                const cursor = input.selectionStart;

                const before =
                    input.value.slice(0, current.start);

                const after =
                    input.value.slice(current.end);

                input.value =
                    before + term + after;

                const newCursor =
                    current.start + term.length;

                input.setSelectionRange(
                    newCursor,
                    newCursor
                );

                /*
                 * Tell Shiny that the input changed.
                 */
                input.dispatchEvent(
                    new Event("input", {
                        bubbles: true
                    })
                );

                closeSuggestions();

                input.focus();
            });

            container.appendChild(item);
        });

        container.style.display = "block";
    }

    function initialise() {
        const input =
            document.getElementById("search_query");

        if (!input) {
            return;
        }

        input.addEventListener("input", function () {
            showSuggestions(input);
        });

        input.addEventListener("keydown", function (event) {
            if (event.key === "Escape") {
                closeSuggestions();
            }
        });

        input.addEventListener("blur", function () {
            /*
             * Small delay allows a suggestion's mousedown
             * handler to run before the menu disappears.
             */
            setTimeout(closeSuggestions, 150);
        });
    }

    /*
     * Shiny custom message handler.
     *
     * Python sends the glossary terms here.
     */
    if (window.Shiny) {
        Shiny.addCustomMessageHandler(
            "glossary_terms",
            function (terms) {
                glossaryTerms = Array.isArray(terms)
                    ? terms
                    : [];

                initialise();
            }
        );
    }

})();
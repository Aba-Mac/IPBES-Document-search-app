(function () {
    "use strict";

    let glossaryTerms = [];

    let autocompleteInitialised = false;


    function getInput() {
        return document.getElementById("search_query");
    }


    function getContainer() {
        return document.getElementById("glossary-autocomplete");
    }


    function closeSuggestions() {
        const container = getContainer();

        if (!container) {
            return;
        }

        container.innerHTML = "";
        container.style.display = "none";
    }


    function getCurrentToken(input) {
        const cursor = input.selectionStart;

        const textBeforeCursor =
            input.value.slice(0, cursor);

        /*
         * Find the current word being typed.
         *
         * Example:
         *
         * biodiversity AND env
         *
         * current token = env
         */
        const match =
            textBeforeCursor.match(/([^\s()]+)$/);

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


    function showSuggestions(input) {
        const container = getContainer();

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
            .filter(function (term) {
                return term
                    .toLowerCase()
                    .startsWith(lowerToken);
            })
            .slice(0, 10);

        if (matches.length === 0) {
            closeSuggestions();
            return;
        }

        container.innerHTML = "";

        matches.forEach(function (term) {

            const item =
                document.createElement("div");

            item.className =
                "glossary-autocomplete-item";

            item.textContent = term;

            item.addEventListener(
                "mousedown",
                function (event) {

                    event.preventDefault();

                    const cursor =
                        input.selectionStart;

                    const before =
                        input.value.slice(
                            0,
                            current.start
                        );

                    const after =
                        input.value.slice(
                            current.end
                        );

                    input.value =
                        before + term + after;

                    const newCursor =
                        current.start + term.length;

                    input.setSelectionRange(
                        newCursor,
                        newCursor
                    );

                    input.dispatchEvent(
                        new Event(
                            "input",
                            {
                                bubbles: true
                            }
                        )
                    );

                    closeSuggestions();

                    input.focus();
                }
            );

            container.appendChild(item);
        });

        container.style.display = "block";
    }


    function initialise() {

        if (autocompleteInitialised) {
            return;
        }

        const input = getInput();

        if (!input) {
            return;
        }

        autocompleteInitialised = true;

        input.addEventListener(
            "input",
            function () {
                showSuggestions(input);
            }
        );

        input.addEventListener(
            "keydown",
            function (event) {

                if (event.key === "Escape") {
                    closeSuggestions();
                }
            }
        );

        input.addEventListener(
            "blur",
            function () {

                setTimeout(
                    closeSuggestions,
                    150
                );
            }
        );
    }


    /*
     * Initialise once the DOM is ready.
     */
    document.addEventListener(
        "DOMContentLoaded",
        function () {
            initialise();
        }
    );


    /*
     * Shiny sends the glossary terms here.
     */
    if (window.Shiny) {

        Shiny.addCustomMessageHandler(
            "glossary_terms",
            function (terms) {

                glossaryTerms =
                    Array.isArray(terms)
                        ? terms
                        : [];

                console.log(
                    "Glossary autocomplete loaded:",
                    glossaryTerms.length,
                    "terms"
                );

                initialise();
            }
        );
    }

})();
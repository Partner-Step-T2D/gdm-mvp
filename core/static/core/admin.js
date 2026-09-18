document.addEventListener("DOMContentLoaded", function () {
    // Section titles you want to toggle
    const sections = ["Personal info", "Permissions", "Important dates"];

    sections.forEach(title => {
        const fs = Array.from(document.querySelectorAll("fieldset.module.aligned"))
            .find(fs => fs.querySelector("h2")?.innerText.trim() === title);

        if (fs) {
            // Start hidden
            fs.style.display = "none";

            // Create toggle link/button
            const toggle = document.createElement("a");
            toggle.href = "#";
            toggle.classList.add("toggle-link");
            toggle.innerText = `Show ${title}`;
            toggle.style.display = "inline-block";
            toggle.style.margin = "10px 0";
            toggle.style.fontWeight = "bold";

            // Insert before the fieldset
            fs.parentNode.insertBefore(toggle, fs);

            toggle.addEventListener("click", function (e) {
                e.preventDefault();
                if (fs.style.display === "none") {
                    fs.style.display = "";
                    toggle.innerText = `Hide ${title}`;
                } else {
                    fs.style.display = "none";
                    toggle.innerText = `Show ${title}`;
                }
            });
        } else {
            console.log(`⚠️ ${title} section not found`);
        }
    });
});

document.addEventListener("DOMContentLoaded", function () {
    const form = document.querySelector("#content-main form");
    const stoppedDateInput = document.querySelector('input[name$="-stopped_date"]');

    if (form && stoppedDateInput) {
        const initialValue = stoppedDateInput.value;

        form.addEventListener("submit", function (e) {
            const valueChanged = stoppedDateInput.value !== initialValue;
            if (stoppedDateInput.value && valueChanged) {
                const confirmed = confirm(
                    "You have selected Stopped Date. This will stop data collection and target generation. " +
                    "This can only be undone by the administrator. Click OK to continue."
                );
                if (!confirmed) {
                    e.preventDefault();
                }
            }
        });
    }
});
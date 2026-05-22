// --- Column toggle ---

const DEFAULT_VISIBLE = [0, 1, 2, 5, 7, 8, 9, 10, 11, 15, 16, 17];

document.addEventListener("DOMContentLoaded", () => {
    const table = document.getElementById("userList");
    const headers = table.querySelectorAll("thead th");
    const menu = document.getElementById("colMenu");

    headers.forEach((th, i) => {
        if (!DEFAULT_VISIBLE.includes(i)) toggleColumn(i, false);

        const li = document.createElement("li");
        li.innerHTML = `<label class="dropdown-item d-flex gap-2" style="cursor:pointer">
                <input type="checkbox" ${DEFAULT_VISIBLE.includes(i) ? "checked" : ""}
                       onchange="toggleColumn(${i}, this.checked)">
                ${th.textContent.trim()}
            </label>`;
        menu.appendChild(li);
    });
});


function toggleColumn(i, visible) {
    document.querySelectorAll(`#userList tr > *:nth-child(${i + 1})`)
        .forEach(cell => cell.style.display = visible ? "" : "none");
}

// --- Sort rows ---
function sortTable(n, is_number = false) {
    let table = document.getElementById("userList");
    let switching = true, dir = "asc", switchcount = 0;

    while (switching) {
        switching = false;
        const rows = table.rows;
        for (let i = 1; i < rows.length - 1; i++) {
            const x = rows[i].getElementsByTagName("TD")[n];
            const y = rows[i + 1].getElementsByTagName("TD")[n];
            const xVal = is_number ? parseFloat(x.innerHTML) : x.innerHTML.toLowerCase();
            const yVal = is_number ? parseFloat(y.innerHTML) : y.innerHTML.toLowerCase();
            const shouldSwitch = dir === "asc" ? xVal > yVal : xVal < yVal;
            if (shouldSwitch) {
                rows[i].parentNode.insertBefore(rows[i + 1], rows[i]);
                switching = true;
                switchcount++;
                break;
            }
        }
        if (!switching && switchcount === 0 && dir === "asc") {
            dir = "desc";
            switching = true;
        }
    }
}
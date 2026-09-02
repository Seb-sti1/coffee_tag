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
function sortTable(n, is_number = false, is_date = false) {
    const table = document.getElementById("userList");
    const tbody = table.tBodies[0];
    const rows = Array.from(tbody.rows);
    const header = table.tHead.rows[0].cells[n];

    // Toggle direction using a data attribute on the header
    const currentDir = header.dataset.sortDir === "asc" ? "desc" : "asc";
    Array.from(table.tHead.rows[0].cells).forEach(th => delete th.dataset.sortDir);
    header.dataset.sortDir = currentDir;

    const getText = (row) => (row.cells[n].innerText ?? row.cells[n].textContent).trim();

    const parseVal = (text) => {
        if (!text || text.toLowerCase() === "none") return null;
        if (is_number) return parseFloat(text);
        if (is_date) return new Date(text);
        return text.toLowerCase();
    };

    const compare = (a, b) => {
        if (a === null && b === null) return 0;
        if (a === null) return -1; // null always smallest
        if (b === null) return 1;
        if (a instanceof Date) return a - b;
        if (typeof a === "number") return a - b;
        return a < b ? -1 : a > b ? 1 : 0;
    };

    rows.sort((rowA, rowB) => {
        const cmp = compare(parseVal(getText(rowA)), parseVal(getText(rowB)));
        return currentDir === "asc" ? cmp : -cmp;
    });

    rows.forEach(row => tbody.appendChild(row));
}
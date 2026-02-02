from flask import Flask, render_template, request, redirect, session
import json, os, random, string

app = Flask(__name__)
app.secret_key = "splitzee-secret-key"
DATA_FILE = "data.json"

# ================= HELPERS =================

def load_data():
    if not os.path.exists(DATA_FILE):
        return {"user": {}, "groups": []}
    with open(DATA_FILE, "r") as f:
        return json.load(f)

def save_data(data):
    with open(DATA_FILE, "w") as f:
        json.dump(data, f, indent=2)

def generate_group_code():
    return "".join(random.choices(string.ascii_uppercase + string.digits, k=6))

def get_group(data, code):
    for g in data.get("groups", []):
        if g.get("group_id") == code:
            return g
    return None

def normalize_data(data):
    data.setdefault("groups", [])
    for g in data["groups"]:
        g.setdefault("expenses", [])
        g.setdefault("settled", False)
        g.setdefault("members", [])

        fixed_members = []
        for m in g["members"]:
            if isinstance(m, str):
                fixed_members.append({"id": m, "name": m})
            else:
                fixed_members.append(m)
        g["members"] = fixed_members

# ================= CALCULATIONS =================

def calculate_balances(group):
    balances = {m["id"]: 0.0 for m in group["members"]}

    for e in group["expenses"]:
        share = e["amount"] / len(e["split_among"])
        for uid in e["split_among"]:
            balances[uid] -= share
        balances[e["paid_by"]] += e["amount"]

    return {k: round(v, 2) for k, v in balances.items()}

def settle_up(balances):
    debtors, creditors, settlements = [], [], []

    for p, amt in balances.items():
        if amt < 0:
            debtors.append([p, -amt])
        elif amt > 0:
            creditors.append([p, amt])

    i = j = 0
    while i < len(debtors) and j < len(creditors):
        pay = min(debtors[i][1], creditors[j][1])
        settlements.append((debtors[i][0], creditors[j][0], round(pay, 2)))
        debtors[i][1] -= pay
        creditors[j][1] -= pay

        if debtors[i][1] <= 0.01:
            i += 1
        if creditors[j][1] <= 0.01:
            j += 1

    return settlements

def total_expense(group):
    return round(sum(e["amount"] for e in group["expenses"]), 2)

# ================= AUTH =================

@app.route("/", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        if request.form.get("action") == "verify_otp":
            session["display_name"] = request.form["display_name"]
            session["user_id"] = request.form["user_id"].lower()
            return redirect("/groups")
    return render_template("login.html")

@app.route("/logout")
def logout():
    session.clear()
    return redirect("/")

# ================= GROUP SELECTION =================

@app.route("/groups")
def group_selection():
    if "user_id" not in session:
        return redirect("/")

    data = load_data()
    normalize_data(data)
    uid = session["user_id"]

    groups = []
    for g in data["groups"]:
        if g["settled"]:
            continue
        if any(m["id"] == uid for m in g["members"]):
            groups.append({
                "code": g["group_id"],
                "name": g["name"]
            })

    return render_template("group_selection.html",
                           username=session["display_name"],
                           groups=groups)

# ================= CREATE GROUP =================

@app.route("/create-group", methods=["GET", "POST"])
def create_group():
    if "user_id" not in session:
        return redirect("/")

    if request.method == "POST":
        data = load_data()
        normalize_data(data)

        code = generate_group_code()
        data["groups"].append({
            "group_id": code,
            "name": request.form["trip_name"],
            "members": [{
                "id": session["user_id"],
                "name": session["display_name"]
            }],
            "expenses": [],
            "settled": False
        })

        save_data(data)
        return redirect(f"/group/{code}")

    return render_template("create_group.html")

# ================= DASHBOARD =================

@app.route("/group/<code>")
def group_dashboard(code):
    if "user_id" not in session:
        return redirect("/")

    data = load_data()
    normalize_data(data)
    group = get_group(data, code)

    if not group:
        return "Group not found", 404

    return render_template("group_dashboard.html",
                           group_name=group["name"],
                           group_code=code,
                           members=group["members"],
                           expenses=group["expenses"])

# ================= SETTLE UP (FIXED) =================

@app.route("/group/<code>/settle")
def group_settle(code):
    if "user_id" not in session:
        return redirect("/")

    data = load_data()
    normalize_data(data)
    group = get_group(data, code)

    if not group:
        return "Group not found", 404

    balances = calculate_balances(group)
    settlements = settle_up(balances)

    return render_template("group_settle.html",
                           group_name=group["name"],
                           group_code=code,
                           settlements=settlements,
                           total=total_expense(group),
                           settled=group["settled"])

# ================= RUN =================

if __name__ == "__main__":
    app.run()

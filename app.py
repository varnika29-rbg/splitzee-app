from flask import Flask, render_template, request, redirect, session, jsonify
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
    for g in data["groups"]:
        if g["group_id"] == code:
            return g
    return None

def normalize_data(data):
    for g in data["groups"]:
        g.setdefault("expenses", [])
        g.setdefault("settled", False)

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
        action = request.form.get("action")

        if action == "generate_otp":
            session["tmp_name"] = request.form["display_name"]
            session["tmp_id"] = request.form["user_id"].lower()
            session["otp"] = str(random.randint(100000, 999999))

            return render_template(
                "login.html",
                step="otp",
                display_name=session["tmp_name"],
                otp=session["otp"]
            )

        if action == "verify_otp":
            if request.form["otp"] == session.get("otp"):
                session["display_name"] = session.pop("tmp_name")
                session["user_id"] = session.pop("tmp_id")
                session.pop("otp")
                return redirect("/groups")

            return render_template(
                "login.html",
                step="otp",
                display_name=session.get("tmp_name"),
                otp=session.get("otp"),
                error="Wrong OTP"
            )

    return render_template("login.html", step="name")

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
        if g.get("settled"):
            continue
        if any(m["id"] == uid for m in g["members"]):
            groups.append({
                "code": g["group_id"],
                "name": g["name"]
            })

    return render_template(
        "group_selection.html",
        username=session["display_name"],
        groups=groups
    )

# ================= CREATE / JOIN =================

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

@app.route("/join-group", methods=["GET", "POST"])
def join_group():
    if "user_id" not in session:
        return redirect("/")

    if request.method == "POST":
        code = request.form["group_code"].upper()
        data = load_data()
        normalize_data(data)

        group = get_group(data, code)
        if not group:
            return "Invalid Group Code"

        if not any(m["id"] == session["user_id"] for m in group["members"]):
            group["members"].append({
                "id": session["user_id"],
                "name": session["display_name"]
            })
            save_data(data)

        return redirect(f"/group/{code}")

    return render_template("join_group.html")

# ================= DASHBOARD =================

@app.route("/group/<code>")
def group_dashboard(code):
    if "user_id" not in session:
        return redirect("/")

    data = load_data()
    normalize_data(data)
    group = get_group(data, code)

    if not group:
        return "Group not found"

    if not any(m["id"] == session["user_id"] for m in group["members"]):
        return "Unauthorized"

    return render_template(
        "group_dashboard.html",
        group_name=group["name"],
        group_code=code,
        members=group["members"],
        expenses=group["expenses"]
    )

# ================= ADD EXPENSE =================

@app.route("/add-expense/<code>", methods=["GET", "POST"])
def add_expense(code):
    if "user_id" not in session:
        return redirect("/")

    data = load_data()
    normalize_data(data)
    group = get_group(data, code)

    if request.method == "POST":
        group["expenses"].append({
            "expense_id": str(random.randint(10000, 99999)),
            "title": request.form["title"],
            "amount": float(request.form["amount"]),
            "paid_by": request.form["paid_by"],
            "split_among": request.form.getlist("split_among")
        })
        save_data(data)
        return redirect(f"/group/{code}")

    return render_template(
        "add_expense.html",
        members=group["members"],
        group_code=code
    )

#================delete expense===============

@app.route("/delete-expense/<group_code>/<expense_id>")
def delete_expense(group_code, expense_id):
    if "user_id" not in session:
        return redirect("/")

    data = load_data()
    normalize_data(data)
    group = get_group(data, group_code)

    if not group:
        return "Group not found"

    group["expenses"] = [
        e for e in group["expenses"]
        if e["expense_id"] != expense_id
    ]

    save_data(data)
    return redirect(f"/group/{group_code}")


#================edit expense==============

@app.route("/edit-expense/<group_code>/<expense_id>", methods=["GET", "POST"])
def edit_expense(group_code, expense_id):
    if "user_id" not in session:
        return redirect("/")

    data = load_data()
    normalize_data(data)
    group = get_group(data, group_code)

    if not group:
        return "Group not found"

    expense = None
    for e in group["expenses"]:
        if e["expense_id"] == expense_id:
            expense = e
            break

    if not expense:
        return "Expense not found"

    if request.method == "POST":
        expense["title"] = request.form["title"]
        expense["amount"] = float(request.form["amount"])
        expense["paid_by"] = request.form["paid_by"]
        expense["split_among"] = request.form.getlist("split_among")

        save_data(data)
        return redirect(f"/group/{group_code}")

    return render_template(
        "edit_expense.html",
        group_code=group_code,
        expense=expense,
        members=group["members"]
    )


# ================= SUMMARY =================

@app.route("/group/<code>/settle")
def group_settle(code):
    if "user_id" not in session:
        return redirect("/")

    data = load_data()
    normalize_data(data)
    group = get_group(data, code)

    balances = calculate_balances(group)
    settlements = settle_up(balances)

    return render_template(
        "group_settle.html",
        group_name=group["name"],
        group_code=code,
        settlements=settlements,
        total=total_expense(group),
        settled=group["settled"]
    )

# ================= HISTORY =================

@app.route("/history")
def history():
    if "user_id" not in session:
        return redirect("/")

    data = load_data()
    normalize_data(data)
    uid = session["user_id"]

    groups = []
    for g in data["groups"]:
        if not g.get("settled"):
            continue
        if any(m["id"] == uid for m in g["members"]):
            groups.append({
                "code": g["group_id"],
                "name": g["name"]
            })

    return render_template(
        "history.html",
        username=session["display_name"],
        groups=groups
    )
#=============profile=============

@app.route("/profile")
def profile():
    if "user_id" not in session:
        return redirect("/")

    data = load_data()
    normalize_data(data)
    uid = session["user_id"]

    name_map = {}
    balances = {}

    for g in data["groups"]:
        if g.get("settled"):
            continue

        for m in g["members"]:
            name_map[m["id"]] = m["name"]

        group_balances = calculate_balances(g)
        for k, v in group_balances.items():
            balances[k] = balances.get(k, 0) + v

    settlements = settle_up(balances)

    to_pay, to_get = [], []
    for owe, get, amt in settlements:
        if owe == uid:
            to_pay.append((name_map.get(get, get), amt))
        if get == uid:
            to_get.append((name_map.get(owe, owe), amt))

    return render_template(
        "profile.html",
        username=session["display_name"],
        to_pay=to_pay,
        to_get=to_get
    )

# ================= DELETE ACCOUNT =================

@app.route("/delete-account", methods=["POST"])
def delete_account():
    save_data({"user": {}, "groups": []})
    session.clear()
    return redirect("/")


# ================= RUN =================

if __name__ == "__main__":
    app.run()

""" Flask site for project app."""

from flask import Flask, render_template, request, session, jsonify, flash, redirect
from flask_debugtoolbar import DebugToolbarExtension
from model import search_recipes, recipe_info_by_id, convert_to_base_unit
from model import User
from model import UserRecipe
from model import Recipe
from model import ShoppingList
from model import ListIngredient
from model import Ingredient
from model import Inventory
from model import connect_to_db, db
from jinja2 import StrictUndefined
import json
import os

app = Flask(__name__)

app.secret_key = os.environ["secretkey"]

# Raises an error if an undefined variable is used in Jinja2
app.jinja_env.undefined = StrictUndefined

@app.route("/")
def homepage():
    """Display homepage."""

    return render_template("homepage.html")


@app.route("/register", methods=["GET"])
def registration_form():
    """ Show registration form."""

    return render_template("registration.html")


@app.route("/register", methods=["POST"])
def register_process():
    """ Verify registration."""

    username = request.form.get("username")
    password = request.form.get("password")

    check_user = User.query.filter(User.username == username).first()

    if check_user:
        flash('This username already exists. Please choose another username.')
        return redirect("/register")
    else:
        new_user = User(username=username, password="")
        new_user.set_password(password)
        db.session.add(new_user)
        db.session.commit()
        return redirect("/login")


@app.route("/login", methods=["GET"])
def login_form():
    """ Show login form."""

    return render_template("login.html")


@app.route("/login", methods=["POST"])
def login_process():
    """ Verify login."""

    username = request.form.get("username")
    password = request.form.get("password")

    check_user = User.query.filter(User.username == username).first()

    if check_user:
        check_password = check_user.check_password(password)
        if check_password:
            session['user_id'] = check_user.user_id
            flash("You are logged in")
            return redirect("/search")
        else:
            flash("Incorrect username and/or password. Please try again.")
            return redirect("/login")
    else:
        flash("Incorrect username and/or password. Please try again.")
        return redirect("/login")


@app.route("/search")
def display_search_form():
    """ Display user's current ingredients."""

    # if user is searching again for recipes, session is still active
    if 'user_id' in session:
        current_ingredients = Inventory.query.filter(Inventory.user_id == session['user_id']).all()

        current_ingredients_list = []

        for ingredient in current_ingredients:
            current_quantity = ingredient.current_quantity
            base_unit = ingredient.ingredients.base_unit
            ingredient_name = ingredient.ingredients.ingredient_name
            current_ingredients_list.append((current_quantity, base_unit, ingredient_name))

        pending_shopping_lists = ShoppingList.query.filter(ShoppingList.has_shopped == False, ShoppingList.user_id == session['user_id']).all()

        pending_recipes = UserRecipe.query.filter(UserRecipe.has_cooked == False, UserRecipe.user_id == session['user_id']).all()

        pending_recipes_list = []

        for user_recipe in pending_recipes:
            recipe_info = recipe_info_by_id(user_recipe.recipe.recipe_id)
            pending_recipes_list.append(recipe_info)

        return render_template("search.html", current_ingredients=current_ingredients_list,
                                              pending_shopping_lists=pending_shopping_lists,
                                              pending_recipes_list=pending_recipes_list,
                                              )
    else:
        return render_template("homepage.html")


@app.route("/recipes")
def show_matching_recipes():
    """ Display recipes using the ingredient selected."""

    diet = request.args.get("diet")
    intolerances = request.args.getlist("intolerances")
    query = request.args.get("query")

    intolerances = "%2C+".join(intolerances)

    recipe_info = search_recipes(diet, intolerances, query)

    return render_template("recipes.html", recipe_info=recipe_info)


@app.route("/user-recipes.json", methods=["POST"])
def show_user_recipes():
    """Keeps track of selected recipes."""

    recipe_ids = request.form.getlist("recipe_ids[]")

    for recipe_id in recipe_ids:
        recipe = db.session.query(UserRecipe).filter(UserRecipe.user_id == session['user_id'], UserRecipe.recipe_id == recipe_id).first()
        if not recipe:
            new_recipe = Recipe(recipe_id=recipe_id,
                                )
            db.session.add(new_recipe)

        new_user_recipe = UserRecipe(user_id=session['user_id'],
                                     recipe_id=recipe_id,
                                     has_cooked=False,
                                     )
        db.session.add(new_user_recipe)

    db.session.commit()

    return jsonify({})


@app.route("/confirm_recipe/<recipe_id>")
def confirm_recipe_cooked(recipe_id):

    recipe_details = recipe_info_by_id(recipe_id)

    return render_template("recipe_info.html", recipe_details=recipe_details)


@app.route("/shopping_list", methods=["POST"])
def show_shopping_list():
    """Display shopping list of missing ingredients."""

    all_user_recipes = db.session.query(UserRecipe.recipe_id).filter(UserRecipe.user_id == session['user_id']).all()
    new_shopping_list = ShoppingList(user_id=session['user_id'],
                                     has_shopped=False,
                                    )
    db.session.add(new_shopping_list)
    db.session.commit()

    aggregated_ingredients = {}

    for recipe_id in all_user_recipes:
        recipe_info = recipe_info_by_id(recipe_id[0])
        
        for ingredient in recipe_info['extendedIngredients']:
            (converted_amount, base_unit) = convert_to_base_unit(ingredient['amount'], ingredient['unitLong'])

            if ingredient['id'] not in aggregated_ingredients:
                aggregated_ingredients[ingredient['id']] = {'quantity': converted_amount, 'unit': base_unit, 'name': ingredient['name']}
            else:
                aggregated_ingredients[ingredient['id']]['quantity'] += converted_amount

    for ingredient_id in aggregated_ingredients:
        ingredient = db.session.query(Ingredient).filter(Ingredient.ingredient_id == ingredient_id).first()

        if not ingredient:
            new_ingredient = Ingredient(ingredient_id=ingredient_id,
                                        ingredient_name=aggregated_ingredients[ingredient_id]['name'],
                                        base_unit=aggregated_ingredients[ingredient_id]['unit'],
                                        )
            db.session.add(new_ingredient)

        new_list_ingredient = ListIngredient(shopping_list_id=new_shopping_list.list_id,
                                             ingredient_id=ingredient_id,
                                             aggregate_quantity=aggregated_ingredients[ingredient_id]['quantity'],
                                             )
        db.session.add(new_list_ingredient)

    db.session.commit()

    user_ingredients = (db.session.query(ListIngredient.aggregate_quantity,
                                         Ingredient.base_unit,
                                         Ingredient.ingredient_name)
                                  .join(Ingredient)
                                  .join(ShoppingList)
                                  .join(User)
                                  .filter(ListIngredient.shopping_list_id == new_shopping_list.list_id)
                                  .filter(User.user_id == session['user_id'])
                                  .order_by(Ingredient.ingredient_name)).all()
    
    return render_template("shopping.html", ingredients=user_ingredients)


@app.route("/confirm_list/<shopping_list_id>")
def confirm_purchases(shopping_list_id):

    list_ingredients = ListIngredient.query.filter(ListIngredient.shopping_list_id == shopping_list_id).all()

    all_ingredients = []

    for ingredient in list_ingredients:
        ingredient_id = ingredient.ingredient_id
        ingredient_qty = ingredient.aggregate_quantity
        ingredient_unit = ingredient.ingredient.base_unit
        ingredient_name = ingredient.ingredient.ingredient_name
        all_ingredients.append((ingredient_id, ingredient_qty, ingredient_unit, ingredient_name))

    return render_template("list_confirmation.html", ingredients=all_ingredients, shopping_list_id=shopping_list_id)


@app.route("/inventory", methods=["POST"])
def add_inventory():
    """ Adds purchased ingredients to inventory."""

    inventory = request.form.get("data")
    inventory_dict = json.loads(inventory)
    shopping_list_id = int(request.form.get("listId"))

    # Add each ingredient to inventory list
    for ingredient_id in inventory_dict:
        new_inventory = Inventory(user_id=session['user_id'],
                                  ingredient_id=int(ingredient_id),
                                  current_quantity=float(inventory_dict[ingredient_id]['ingredientQty']),
                                  )
        db.session.add(new_inventory)

    # Change status of shopping list since list has been used by user
    shopping_list = ShoppingList.query.filter(ShoppingList.list_id == shopping_list_id).one()
    shopping_list.has_shopped = True

    db.session.commit()

    return jsonify({'success': True})


@app.route("/logout")
def logs_user_out():
    """ Logs out user."""

    session.pop('user_id', None)

    return render_template("/logout.html")


if __name__ == "__main__":
    # the toolbar is only enabled in debug mode:
    app.debug = True
    connect_to_db(app)
    DebugToolbarExtension(app)
    app.run(host="0.0.0.0")
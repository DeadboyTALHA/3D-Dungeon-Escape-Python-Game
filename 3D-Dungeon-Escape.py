from OpenGL.GL import *
from OpenGL.GLUT import *
from OpenGL.GLU import *
import math, random, time, json, os

WIN_W, WIN_H = 1000, 800
FOV_Y = 75
NEAR_CLIP = 0.1
FAR_CLIP = 2000

CELL = 120
WALL_H = 100
DUNGEON_ROWS = 11
DUNGEON_COLS = 11

TILE_EMPTY = 0
TILE_WALL = 1
TILE_DOOR = 2
TILE_LEVER = 3
TILE_ITEM = 4
TILE_EXIT = 5

ITEM_KEY = "key"
ITEM_HEALTH_PACK = "health_pack"
ENEMY_MELEE = "melee"
ENEMY_RANGED = "ranged"
ENEMY_FAST = "fast"
ENEMY_BOSS = "boss"

WEAPONS = {
    "sword": {"damage": 35, "cooldown": 0.6, "range": CELL * 1.5, "color": (0.78, 0.78, 0.9)},
    "crossbow": {"damage": 50, "cooldown": 1.2, "range": CELL * 8, "color": (0.55, 0.35, 0.15)},
}

game = {
    "player_x": 0, "player_y": 0, "player_z": 50,
    "yaw": 0, "pitch": 0,
    "health": 100, "max_health": 100,
    "stamina": 100, "max_stamina": 100,
    "inventory": [],
    "current_weapon": "sword",
    "attack_cooldown": 0,
    "bob_time": 0, "bob_offset": 0,
    "is_moving": False, "is_running": False,
    "enemies": [], "projectiles": [],
    "level": 1,
    "grid": [], "doors": [], "levers": [],
    "world_items": [],
    "explored": set(),
    "show_minimap": True,
    "game_over": False, "victory": False,
    "exit_position": (0, 0),
    "first_person": False,
    "camera_yaw": 50,
    "camera_pitch": 70,
    "camera_distance": 500,
}

keys_pressed = set()
last_frame_time = time.time()
delta_time = 0
damage_flash = 0
SAVE_FILE = "dungeon_save.json"

PLAYER_RADIUS = 42
PLAYER_BODY_R = 25
PLAYER_HEAD_R = 15
ROTATION_SPEED = 120

def generate_dungeon(seed=None):
    if seed is None:
        seed = random.randint(0, 99999)
    random_gen = random.Random(seed)
    rows, cols = DUNGEON_ROWS, DUNGEON_COLS
    level_grid = [[TILE_WALL] * cols for _ in range(rows)]
    
    def carve_path(row, col):
        directions = [(0,2),(0,-2),(2,0),(-2,0)]
        random_gen.shuffle(directions)
        for dr, dc in directions:
            new_row, new_col = row + dr, col + dc
            if 1 <= new_row < rows-1 and 1 <= new_col < cols-1 and level_grid[new_row][new_col] == TILE_WALL:
                level_grid[row + dr//2][col + dc//2] = TILE_EMPTY
                level_grid[new_row][new_col] = TILE_EMPTY
                carve_path(new_row, new_col)
    
    level_grid[1][1] = TILE_EMPTY
    carve_path(1, 1)
    
    dead_ends = []
    for row in range(1, rows-1):
        for col in range(1, cols-1):
            if level_grid[row][col] == TILE_EMPTY and (row,col) != (1,1):
                neighbor_count = 0
                for dr, dc in [(0,1),(0,-1),(1,0),(-1,0)]:
                    if level_grid[row+dr][col+dc] == TILE_EMPTY:
                        neighbor_count += 1
                if neighbor_count == 1:
                    dead_ends.append((row,col))
    
    if dead_ends:
        exit_row, exit_col = random_gen.choice(dead_ends)
    else:
        exit_row, exit_col = rows-2, cols-2
    level_grid[exit_row][exit_col] = TILE_EXIT
    
    empty_cells = []
    for row in range(1, rows-1):
        for col in range(1, cols-1):
            if level_grid[row][col] == TILE_EMPTY and abs(row-1)+abs(col-1) > 4 and abs(row-exit_row)+abs(col-exit_col) > 4:
                empty_cells.append((row,col))
    
    door_cells = random_gen.sample(empty_cells, min(3, len(empty_cells)))
    level_doors = []
    for row,col in door_cells:
        level_grid[row][col] = TILE_DOOR
        level_doors.append({"row":row,"col":col,"locked":random_gen.choice([True, False]),"open":False})
    
    lever_pool = [cell for cell in empty_cells if cell not in door_cells]
    level_levers = []
    for door_index, door in enumerate(level_doors):
        if door["locked"] and lever_pool:
            lever_row, lever_col = random_gen.choice(lever_pool)
            lever_pool.remove((lever_row, lever_col))
            level_grid[lever_row][lever_col] = TILE_LEVER
            level_levers.append({"row":lever_row,"col":lever_col,"activated":False,"target_door":door_index})
    
    world_items = []
    item_pool = []
    for row,col in empty_cells:
        if (row,col) not in door_cells and level_grid[row][col] == TILE_EMPTY:
            item_pool.append((row,col))
    
    for row,col in random_gen.sample(item_pool, min(6,len(item_pool))):
        item_type = random_gen.choice([ITEM_KEY, ITEM_HEALTH_PACK])
        world_items.append({"row":row,"col":col,"type":item_type,"collected":False})
    
    level_enemies = spawn_enemies(level_grid, random_gen, rows, cols, exit_row, exit_col)
    return level_grid, level_doors, level_levers, world_items, level_enemies, (exit_row, exit_col)

def spawn_enemies(level_grid, random_gen, rows, cols, exit_row, exit_col):
    current_level = game["level"]
    available_cells = []
    for row in range(1, rows-1):
        for col in range(1, cols-1):
            if level_grid[row][col] == TILE_EMPTY and abs(row-1)+abs(col-1) > 3:
                available_cells.append((row,col))
    
    enemy_count = min(4 + current_level*2, len(available_cells))
    chosen_cells = random_gen.sample(available_cells, enemy_count)
    
    enemy_types = [ENEMY_MELEE]*4 + [ENEMY_RANGED]*3 + [ENEMY_FAST]*3
    enemies_list = []
    
    for row,col in chosen_cells:
        enemy_type = random_gen.choice(enemy_types)
        world_x = col*CELL + CELL//2
        world_y = row*CELL + CELL//2
        enemies_list.append(create_enemy(enemy_type, world_x, world_y))
    
    if current_level % 3 == 0 and available_cells:
        boss_x = exit_col*CELL + CELL//2
        boss_y = exit_row*CELL + CELL//2
        enemies_list.append(create_enemy(ENEMY_BOSS, boss_x, boss_y))
    
    return enemies_list

def create_enemy(enemy_type, world_x, world_y):
    enemy_stats = {
        ENEMY_MELEE: {"hp":80, "max_hp":80, "speed":60, "damage":15, "attack_range":CELL*0.8, "color":(0.8,0.2,0.2)},
        ENEMY_RANGED: {"hp":50, "max_hp":50, "speed":40, "damage":20, "attack_range":CELL*5, "color":(0.8,0.6,0.1)},
        ENEMY_FAST: {"hp":40, "max_hp":40, "speed":110, "damage":10, "attack_range":CELL*0.9, "color":(0.2,0.8,0.4)},
        ENEMY_BOSS: {"hp":400, "max_hp":400, "speed":50, "damage":30, "attack_range":CELL*1.2, "color":(0.6,0,0.8)},
    }[enemy_type]
    
    return {
        "type": enemy_type,
        "x": float(world_x), "y": float(world_y), "z": 50,
        "hp": enemy_stats["hp"], "max_hp": enemy_stats["max_hp"],
        "speed": enemy_stats["speed"], "damage": enemy_stats["damage"],
        "attack_range": enemy_stats["attack_range"], "color": enemy_stats["color"],
        "attack_cooldown": 0, "hit_flash": 0,
        "alive": True, "phase": 1, "special_timer": 0,
    }

def load_level(level_number):
    seed = level_number * 7 + 423
    level_grid, level_doors, level_levers, world_items, enemies_list, exit_position = generate_dungeon(seed)
    
    game["player_x"] = 1*CELL + CELL//2
    game["player_y"] = 1*CELL + CELL//2
    game["player_z"] = 50
    game["yaw"] = 0
    game["pitch"] = 0
    game["grid"] = level_grid
    game["doors"] = level_doors
    game["levers"] = level_levers
    game["world_items"] = world_items
    game["enemies"] = enemies_list
    game["projectiles"] = []
    game["explored"] = set()
    game["exit_position"] = exit_position
    game["attack_cooldown"] = 0
    game["bob_time"] = 0
    game["bob_offset"] = 0
    game["game_over"] = False
    game["victory"] = False
    game["stamina"] = game["max_stamina"]

def world_to_cell(world_x, world_y):
    return int(world_y // CELL), int(world_x // CELL)

def cell_center(row, col):
    return col*CELL + CELL//2, row*CELL + CELL//2

def is_cell_walkable(row, col):
    level_grid = game["grid"]
    if row < 0 or col < 0 or row >= len(level_grid) or col >= len(level_grid[0]):
        return False
    
    tile_type = level_grid[row][col]
    if tile_type == TILE_WALL:
        return False
    if tile_type == TILE_DOOR:
        for door in game["doors"]:
            if door["row"] == row and door["col"] == col:
                return door["open"]
        return False
    return True

def is_position_walkable(world_x, world_y):
    row, col = world_to_cell(world_x, world_y)
    return is_cell_walkable(row, col)

def get_forward_direction():
    angle_rad = math.radians(game["yaw"])
    return math.cos(angle_rad), math.sin(angle_rad)

WALK_SPEED = 150
RUN_SPEED = 240
sprint_active = False

def update_player(delta_time):
    global damage_flash, sprint_active
    
    if game["game_over"] or game["victory"]:
        return
    
    is_sprinting = sprint_active and game["stamina"] > 0
    current_speed = RUN_SPEED if is_sprinting else WALK_SPEED
    
    if is_sprinting:
        game["stamina"] = max(0, game["stamina"] - 30 * delta_time)
        if game["stamina"] <= 0:
            sprint_active = False
    else:
        game["stamina"] = min(game["max_stamina"], game["stamina"] + 15 * delta_time)
    
    # NEW MOVEMENT: W/S for forward/backward, A/D for rotation
    forward_x, forward_y = get_forward_direction()
    move_x, move_y = 0, 0
    moving = False
    
    # Rotation with A/D keys
    if b'a' in keys_pressed:
        game["yaw"] += ROTATION_SPEED * delta_time
    if b'd' in keys_pressed:
        game["yaw"] -= ROTATION_SPEED * delta_time
    
    # Forward/Backward with W/S keys
    if b'w' in keys_pressed:
        move_x += forward_x
        move_y += forward_y
        moving = True
    if b's' in keys_pressed:
        move_x -= forward_x
        move_y -= forward_y
        moving = True
    
    game["is_moving"] = moving
    game["is_running"] = is_sprinting and moving
    
    if moving:
        move_length = math.sqrt(move_x*move_x + move_y*move_y)
        if move_length > 0:
            move_x /= move_length
            move_y /= move_length
        
        new_x = game["player_x"] + move_x * current_speed * delta_time
        new_y = game["player_y"] + move_y * current_speed * delta_time
        
        if can_move_to(new_x, new_y):
            game["player_x"], game["player_y"] = new_x, new_y
        elif can_move_to(new_x, game["player_y"]):
            game["player_x"] = new_x
        elif can_move_to(game["player_x"], new_y):
            game["player_y"] = new_y
    
    if game["is_moving"]:
        bob_speed = 8 if not is_sprinting else 14
        game["bob_time"] += delta_time * bob_speed
        game["bob_offset"] = math.sin(game["bob_time"]) * 5
    else:
        game["bob_time"] *= 0.9
        game["bob_offset"] = math.sin(game["bob_time"]) * 5
    
    if game["attack_cooldown"] > 0:
        game["attack_cooldown"] -= delta_time
    if damage_flash > 0:
        damage_flash -= delta_time
    
    player_row, player_col = world_to_cell(game["player_x"], game["player_y"])
    if (player_row, player_col) == game["exit_position"]:
        game["victory"] = True
    game["explored"].add((player_row, player_col))

def can_move_to(x, y):
    radius = PLAYER_RADIUS
    for check_x, check_y in [(x-radius, y-radius), (x+radius, y-radius), (x-radius, y+radius), (x+radius, y+radius)]:
        row, col = world_to_cell(check_x, check_y)
        if not is_cell_walkable(row, col):
            return False
    return True

def player_attack():
    if game["attack_cooldown"] > 0:
        return
    
    weapon_name = game["current_weapon"]
    weapon_data = WEAPONS[weapon_name]
    game["attack_cooldown"] = weapon_data["cooldown"]
    
    if weapon_name == "sword":
        sword_attack(weapon_data)
    elif weapon_name == "crossbow":
        shoot_bolt()

def sword_attack(weapon_data):
    forward_x, forward_y = get_forward_direction()
    
    for enemy in game["enemies"]:
        if not enemy["alive"]:
            continue
        
        enemy_dx = enemy["x"] - game["player_x"]
        enemy_dy = enemy["y"] - game["player_y"]
        distance = math.sqrt(enemy_dx*enemy_dx + enemy_dy*enemy_dy)
        
        if distance > weapon_data["range"]:
            continue
        
        dot_product = (enemy_dx*forward_x + enemy_dy*forward_y) / (distance + 0.001)
        if dot_product > 0.7:
            damage_enemy(enemy, weapon_data["damage"])

def shoot_bolt():
    forward_x, forward_y = get_forward_direction()
    game["projectiles"].append({
        "x": game["player_x"], "y": game["player_y"], "z": game["player_z"],
        "dx": forward_x, "dy": forward_y, "dz": 0,
        "speed": 400, "damage": WEAPONS["crossbow"]["damage"],
        "owner": "player", "alive": True,
    })

def switch_weapon():
    weapon_list = list(WEAPONS.keys())
    current_index = weapon_list.index(game["current_weapon"])
    game["current_weapon"] = weapon_list[(current_index + 1) % len(weapon_list)]

def player_interact():
    forward_x, forward_y = get_forward_direction()
    check_x = game["player_x"] + forward_x * (CELL * 0.8)
    check_y = game["player_y"] + forward_y * (CELL * 0.8)
    row, col = world_to_cell(check_x, check_y)
    
    level_grid = game["grid"]
    if row < 0 or col < 0 or row >= len(level_grid) or col >= len(level_grid[0]):
        return
    
    tile_type = level_grid[row][col]
    
    if tile_type == TILE_DOOR:
        for door in game["doors"]:
            if door["row"] == row and door["col"] == col and not door["open"]:
                if not door["locked"]:
                    door["open"] = True
                elif ITEM_KEY in game["inventory"]:
                    game["inventory"].remove(ITEM_KEY)
                    door["locked"] = False
                    door["open"] = True
                break
    
    elif tile_type == TILE_LEVER:
        for lever in game["levers"]:
            if lever["row"] == row and lever["col"] == col and not lever["activated"]:
                lever["activated"] = True
                target_door_index = lever["target_door"]
                if 0 <= target_door_index < len(game["doors"]):
                    game["doors"][target_door_index]["locked"] = False
                    game["doors"][target_door_index]["open"] = True
                game["grid"][row][col] = TILE_EMPTY
                break

def update_items():
    player_row, player_col = world_to_cell(game["player_x"], game["player_y"])
    
    for item in game["world_items"]:
        if item["collected"]:
            continue
        if item["row"] == player_row and item["col"] == player_col:
            item["collected"] = True
            game["grid"][player_row][player_col] = TILE_EMPTY
            
            if item["type"] == ITEM_KEY:
                game["inventory"].append(ITEM_KEY)
            elif item["type"] == ITEM_HEALTH_PACK:
                game["health"] = min(game["max_health"], game["health"] + 40)

def update_enemies(delta_time):
    global damage_flash
    
    for enemy in game["enemies"]:
        if not enemy["alive"]:
            continue
        
        enemy["attack_cooldown"] = max(0, enemy["attack_cooldown"] - delta_time)
        enemy["hit_flash"] = max(0, enemy["hit_flash"] - delta_time)
        
        enemy_x, enemy_y = enemy["x"], enemy["y"]
        player_x, player_y = game["player_x"], game["player_y"]
        dx, dy = player_x - enemy_x, player_y - enemy_y
        distance = math.sqrt(dx*dx + dy*dy)
        
        if distance <= enemy["attack_range"] and enemy["attack_cooldown"] <= 0:
            if enemy["type"] in (ENEMY_MELEE, ENEMY_FAST, ENEMY_BOSS):
                game["health"] -= enemy["damage"]
                enemy["attack_cooldown"] = 1
                damage_flash = 0.3
            elif enemy["type"] == ENEMY_RANGED:
                if distance > 0.01:
                    enemy_shoot(enemy, dx/distance, dy/distance)
                enemy["attack_cooldown"] = 1.8
            
            if enemy["type"] == ENEMY_BOSS:
                if enemy["hp"] <= enemy["max_hp"] // 2 and enemy["phase"] == 1:
                    enemy["phase"] = 2
                    enemy["speed"] *= 1.6
                enemy["special_timer"] = max(0, enemy["special_timer"] - delta_time)
                if enemy["phase"] == 2 and enemy["special_timer"] <= 0:
                    if distance > 0.01:
                        enemy_shoot(enemy, dx/distance, dy/distance)
                    enemy["special_timer"] = 2
        
        if distance > 5:
            norm_dx, norm_dy = dx/distance, dy/distance
            new_x = enemy_x + norm_dx * enemy["speed"] * delta_time
            new_y = enemy_y + norm_dy * enemy["speed"] * delta_time
            
            if not is_position_walkable(new_x, new_y):
                if is_position_walkable(enemy_x + norm_dx * enemy["speed"] * delta_time, enemy_y):
                    new_x = enemy_x + norm_dx * enemy["speed"] * delta_time
                else:
                    new_x = enemy_x
                if is_position_walkable(enemy_x, enemy_y + norm_dy * enemy["speed"] * delta_time):
                    new_y = enemy_y + norm_dy * enemy["speed"] * delta_time
                else:
                    new_y = enemy_y
            
            enemy["x"], enemy["y"] = new_x, new_y

def enemy_shoot(enemy, direction_x, direction_y):
    game["projectiles"].append({
        "x": enemy["x"], "y": enemy["y"], "z": 50,
        "dx": direction_x, "dy": direction_y, "dz": 0,
        "speed": 160, "damage": enemy["damage"],
        "owner": "enemy", "alive": True,
    })

def update_projectiles(delta_time):
    global damage_flash
    
    for projectile in game["projectiles"]:
        if not projectile["alive"]:
            continue
        
        projectile["x"] += projectile["dx"] * projectile["speed"] * delta_time
        projectile["y"] += projectile["dy"] * projectile["speed"] * delta_time
        
        row, col = world_to_cell(projectile["x"], projectile["y"])
        if not is_cell_walkable(row, col):
            projectile["alive"] = False
            continue
        
        if projectile["owner"] == "player":
            for enemy in game["enemies"]:
                if not enemy["alive"]:
                    continue
                dx = projectile["x"] - enemy["x"]
                dy = projectile["y"] - enemy["y"]
                if math.sqrt(dx*dx + dy*dy) < 40:
                    damage_enemy(enemy, projectile["damage"])
                    projectile["alive"] = False
                    break
        else:
            dx = projectile["x"] - game["player_x"]
            dy = projectile["y"] - game["player_y"]
            if math.sqrt(dx*dx + dy*dy) < PLAYER_RADIUS:
                game["health"] -= projectile["damage"]
                damage_flash = 0.25
                projectile["alive"] = False
    
    game["projectiles"] = [p for p in game["projectiles"] if p["alive"]]
    
    if game["health"] <= 0:
        game["health"] = 0
        game["game_over"] = True

def damage_enemy(enemy, damage_amount):
    enemy["hp"] -= damage_amount
    enemy["hit_flash"] = 0.2
    if enemy["hp"] <= 0:
        enemy["alive"] = False

def setup_camera():
    glMatrixMode(GL_PROJECTION)
    glLoadIdentity()
    gluPerspective(FOV_Y, WIN_W/WIN_H, NEAR_CLIP, FAR_CLIP)
    glMatrixMode(GL_MODELVIEW)
    glLoadIdentity()
    
    player_x = game["player_x"]
    player_y = game["player_y"]
    
    if game["first_person"]:
        eye_z = game["player_z"] + game["bob_offset"]
        yaw_rad = math.radians(game["yaw"])
        pitch_rad = math.radians(game["pitch"])
        look_x = player_x + math.cos(yaw_rad) * math.cos(pitch_rad)
        look_y = player_y + math.sin(yaw_rad) * math.cos(pitch_rad)
        look_z = eye_z + math.sin(pitch_rad)
        gluLookAt(player_x, player_y, eye_z, look_x, look_y, look_z, 0, 0, 1)
    else:
        camera_yaw_rad = math.radians(game["camera_yaw"])
        camera_pitch_rad = math.radians(game["camera_pitch"])
        camera_distance = game["camera_distance"]
        
        camera_x = player_x - math.cos(camera_yaw_rad) * math.cos(camera_pitch_rad) * camera_distance
        camera_y = player_y - math.sin(camera_yaw_rad) * math.cos(camera_pitch_rad) * camera_distance
        camera_z = game["player_z"] + math.sin(camera_pitch_rad) * camera_distance
        
        target_z = game["player_z"] + PLAYER_BODY_R
        gluLookAt(camera_x, camera_y, camera_z, player_x, player_y, target_z, 0, 0, 1)

def draw_dungeon():
    level_grid = game["grid"]
    rows = len(level_grid)
    cols = len(level_grid[0]) if rows else 0
    player_row, player_col = world_to_cell(game["player_x"], game["player_y"])
    view_range = 6
    
    for row in range(max(0, player_row - view_range), min(rows, player_row + view_range + 1)):
        for col in range(max(0, player_col - view_range), min(cols, player_col + view_range + 1)):
            tile_type = level_grid[row][col]
            x0 = col * CELL
            y0 = row * CELL
            
            if tile_type == TILE_WALL:
                draw_wall_cell(x0, y0)
            elif tile_type in (TILE_EMPTY, TILE_EXIT, TILE_ITEM, TILE_LEVER):
                draw_floor_cell(x0, y0, tile_type)
            elif tile_type == TILE_DOOR:
                draw_door_cell(row, col, x0, y0)

def draw_floor_cell(x0, y0, tile_type):
    x1, y1 = x0 + CELL, y0 + CELL
    
    if tile_type == TILE_EXIT:
        glColor3f(0.1, 0.6, 0.2)
    elif tile_type == TILE_LEVER:
        glColor3f(0.5, 0.35, 0.1)
    else:
        glColor3f(0.22, 0.20, 0.18)
    
    glBegin(GL_QUADS)
    glVertex3f(x0, y0, 0)
    glVertex3f(x1, y0, 0)
    glVertex3f(x1, y1, 0)
    glVertex3f(x0, y1, 0)
    glEnd()
    
    if tile_type == TILE_LEVER:
        draw_lever(x0 + CELL//2, y0 + CELL//2, 0)

def draw_wall_cell(x0, y0):
    center_x = x0 + CELL//2
    center_y = y0 + CELL//2
    center_z = WALL_H // 2
    glColor3f(0.32, 0.28, 0.25)
    glPushMatrix()
    glTranslatef(center_x, center_y, center_z)
    glScalef(CELL, CELL, WALL_H)
    glutSolidCube(1)
    glPopMatrix()

def draw_door_cell(row, col, x0, y0):
    is_open = False
    is_locked = False
    
    for door in game["doors"]:
        if door["row"] == row and door["col"] == col:
            is_open = door["open"]
            is_locked = door["locked"]
            break
    
    center_x = x0 + CELL//2
    center_y = y0 + CELL//2
    
    if is_open:
        glColor3f(0.35, 0.22, 0.08)
        glPushMatrix()
        glTranslatef(center_x, center_y, 4)
        glScalef(CELL, CELL, 8)
        glutSolidCube(1)
        glPopMatrix()
    else:
        if is_locked:
            glColor3f(0.55, 0.18, 0.18)
        else:
            glColor3f(0.38, 0.22, 0.08)
        
        glPushMatrix()
        glTranslatef(center_x, center_y, WALL_H//2)
        glScalef(CELL, CELL, WALL_H)
        glutSolidCube(1)
        glPopMatrix()
        
        if is_locked:
            glColor3f(1, 0.82, 0)
            glPushMatrix()
            glTranslatef(center_x, center_y, WALL_H//2)
            glutSolidSphere(7, 8, 8)
            glPopMatrix()

def draw_lever(world_x, world_y, world_z):
    quadric = gluNewQuadric()
    glColor3f(0.45, 0.45, 0.45)
    glPushMatrix()
    glTranslatef(world_x, world_y, world_z + 18)
    gluCylinder(quadric, 4, 4, 28, 8, 1)
    glTranslatef(0, 0, 28)
    glRotatef(45, 1, 0, 0)
    glColor3f(0.7, 0.4, 0.1)
    gluCylinder(quadric, 3, 2, 18, 8, 1)
    glPopMatrix()

def draw_third_person_weapon(quadric):
    swing = max(0, game["attack_cooldown"])
    
    glPushMatrix()
    glTranslatef(0, -(PLAYER_BODY_R + 8), PLAYER_BODY_R * 1.4)
    glTranslatef(28, 0, 0)
    
    if game["current_weapon"] == "sword":
        glRotatef(90, 0, 1, 0)
        glRotatef(-20, 1, 0, 0)
        glRotatef(swing * 60, 1, 0, 0)
        
        glColor3f(0.35, 0.20, 0.08)
        glPushMatrix()
        gluCylinder(quadric, 2.5, 2.5, 10, 8, 2)
        glPopMatrix()
        
        glColor3f(0.70, 0.68, 0.30)
        glPushMatrix()
        glTranslatef(0, 0, 10)
        glScalef(5, 1.5, 1.5)
        glutSolidCube(1)
        glPopMatrix()
        
        glColor3f(0.82, 0.84, 0.92)
        glPushMatrix()
        glTranslatef(0, 0, 12)
        glScalef(1.2, 1.2, 18)
        glutSolidCube(1)
        glPopMatrix()
    else:
        glTranslatef(10, 0, 0)
        glRotatef(90, 0, 1, 0)
        glRotatef(-10, 1, 0, 0)
        glRotatef(swing * 20, 1, 0, 0)
        
        glColor3f(0.48, 0.30, 0.12)
        glPushMatrix()
        glScalef(6, 2.5, 2.5)
        glutSolidCube(1)
        glPopMatrix()
        
        glColor3f(0.55, 0.35, 0.15)
        for side in (-1, 1):
            glPushMatrix()
            glTranslatef(0, side * 5, 0)
            glScalef(1, 9, 1)
            glutSolidCube(1)
            glPopMatrix()
    
    glPopMatrix()

def draw_player():
    if game["first_person"]:
        return
    
    player_x, player_y = game["player_x"], game["player_y"]
    quadric = gluNewQuadric()
    
    glPushMatrix()
    glTranslatef(player_x, player_y, 0)
    glRotatef(game["yaw"], 0, 0, 1)
    
    glColor3f(0.25, 0.50, 0.22)
    glPushMatrix()
    glTranslatef(0, 0, PLAYER_BODY_R)
    glutSolidSphere(PLAYER_BODY_R, 16, 12)
    glPopMatrix()
    
    glColor3f(0.55, 0.55, 0.60)
    glPushMatrix()
    glTranslatef(PLAYER_BODY_R*0.6, 0, PLAYER_BODY_R)
    glScalef(6, PLAYER_BODY_R*1.1, PLAYER_BODY_R*1.2)
    glutSolidCube(1)
    glPopMatrix()
    
    glColor3f(0.80, 0.60, 0.45)
    for side in (-1, 1):
        glPushMatrix()
        glTranslatef(0, side*(PLAYER_BODY_R+3), PLAYER_BODY_R*1.1)
        glRotatef(90, 0, 1, 0)
        gluCylinder(quadric, 4, 2, PLAYER_BODY_R*1.6, 8, 4)
        glPopMatrix()
    
    glColor3f(0.80, 0.60, 0.45)
    glPushMatrix()
    glTranslatef(0, 0, PLAYER_BODY_R*2 - 2)
    glRotatef(-90, 1, 0, 0)
    gluCylinder(quadric, 4, 4, 7, 8, 2)
    glPopMatrix()
    
    glColor3f(0.80, 0.60, 0.45)
    glPushMatrix()
    glTranslatef(0, 0, PLAYER_BODY_R*2 + PLAYER_HEAD_R + 5)
    glutSolidSphere(PLAYER_HEAD_R, 14, 10)
    glPopMatrix()
    
    glColor3f(0.30, 0.35, 0.40)
    glPushMatrix()
    glTranslatef(PLAYER_HEAD_R*0.55, 0, PLAYER_BODY_R*2 + PLAYER_HEAD_R + 5)
    glScalef(5, PLAYER_HEAD_R*1.2, PLAYER_HEAD_R*0.7)
    glutSolidCube(1)
    glPopMatrix()
    
    draw_third_person_weapon(quadric)
    glPopMatrix()

def draw_enemies():
    quadric = gluNewQuadric()
    
    for enemy in game["enemies"]:
        if not enemy["alive"]:
            continue
        
        enemy_x, enemy_y = enemy["x"], enemy["y"]
        
        if enemy["hit_flash"] > 0:
            color = (1, 0, 0)
        else:
            color = enemy["color"]
        
        is_boss = enemy["type"] == ENEMY_BOSS
        body_radius = 35 if is_boss else 25
        head_radius = int(body_radius * 0.55)
        
        glPushMatrix()
        glTranslatef(enemy_x, enemy_y, 0)
        
        glColor3f(*color)
        glPushMatrix()
        glTranslatef(0, 0, body_radius)
        glutSolidSphere(body_radius, 14, 10)
        glPopMatrix()
        
        glColor3f(color[0]*0.7, color[1]*0.7, color[2]*0.7)
        glPushMatrix()
        glTranslatef(0, 0, body_radius*2 + head_radius)
        glutSolidSphere(head_radius, 12, 8)
        glPopMatrix()
        
        if is_boss:
            glColor3f(0.9, 0.8, 0)
            for side in (-1, 1):
                glPushMatrix()
                glTranslatef(0, side*(head_radius*0.7), body_radius*2 + head_radius*1.8)
                glRotatef(side*30, 1, 0, 0)
                gluCylinder(quadric, 3, 0, 18, 6, 3)
                glPopMatrix()
        
        glPopMatrix()
        draw_health_bar(enemy_x, enemy_y, body_radius*2 + head_radius*2 + 20, enemy["hp"], enemy["max_hp"])

def draw_health_bar(x, y, height, current_hp, max_hp):
    bar_width = 55
    health_ratio = max(0, current_hp / max_hp)
    z_pos = height + 10
    
    glLineWidth(3.5)
    glBegin(GL_LINES)
    glColor3f(0.35, 0, 0)
    glVertex3f(x - bar_width/2, y, z_pos)
    glVertex3f(x + bar_width/2, y, z_pos)
    glColor3f(0, 0.88, 0.15)
    glVertex3f(x - bar_width/2, y, z_pos)
    glVertex3f(x - bar_width/2 + bar_width * health_ratio, y, z_pos)
    glEnd()
    glLineWidth(1)

def draw_items():
    quadric = gluNewQuadric()
    
    for item in game["world_items"]:
        if item["collected"]:
            continue
        
        item_x, item_y = cell_center(item["row"], item["col"])
        
        if item["type"] == ITEM_KEY:
            draw_key(item_x, item_y, quadric)
        else:
            draw_health_tablet(item_x, item_y)

def draw_key(x, y, quadric):
    glPushMatrix()
    glTranslatef(x, y, 22)
    glRotatef((time.time()*80) % 360, 0, 0, 1)
    glColor3f(1, 0.82, 0)
    
    ring_radius = 9
    for i in range(12):
        angle = i * (360/12)
        rad_angle = math.radians(angle)
        ring_x = ring_radius * math.cos(rad_angle)
        ring_y = ring_radius * math.sin(rad_angle)
        glPushMatrix()
        glTranslatef(ring_x, ring_y, 0)
        glutSolidSphere(2.8, 6, 5)
        glPopMatrix()
    
    glPushMatrix()
    glTranslatef(0, -(ring_radius + 10), 0)
    glRotatef(90, 1, 0, 0)
    gluCylinder(quadric, 2.2, 2.2, 18, 7, 2)
    glPopMatrix()
    
    for tooth_z in (0, 6):
        glPushMatrix()
        glTranslatef(4, -(ring_radius + 14 + tooth_z), 0)
        glScalef(4, 2.5, 2.5)
        glutSolidCube(1)
        glPopMatrix()
    
    glPopMatrix()

def draw_health_tablet(x, y):
    glPushMatrix()
    glTranslatef(x, y, 18)
    glRotatef((time.time()*60) % 360, 0, 0, 1)
    glRotatef(90, 0, 1, 0)
    
    quadric = gluNewQuadric()
    cap_radius = 7
    cylinder_length = 10
    
    glColor3f(0.95, 0.95, 0.95)
    gluCylinder(quadric, cap_radius, cap_radius, cylinder_length, 10, 4)
    
    glColor3f(0.9, 0.15, 0.15)
    glutSolidSphere(cap_radius, 10, 7)
    
    glPushMatrix()
    glTranslatef(0, 0, cylinder_length)
    glColor3f(0.95, 0.95, 0.95)
    glutSolidSphere(cap_radius, 10, 7)
    glPopMatrix()
    
    glColor3f(0.9, 0.1, 0.1)
    for rotation in (0, 90):
        glPushMatrix()
        glTranslatef(0, 0, cylinder_length + 1)
        glRotatef(rotation, 0, 0, 1)
        glScalef(2, 10, 2)
        glutSolidCube(1)
        glPopMatrix()
    
    glPopMatrix()

def draw_projectiles():
    quadric = gluNewQuadric()
    
    for projectile in game["projectiles"]:
        if not projectile["alive"]:
            continue
        
        if projectile["owner"] == "player":
            glColor3f(0.2, 0.9, 0.9)
        else:
            glColor3f(0.9, 0.5, 0.1)
        
        glPushMatrix()
        glTranslatef(projectile["x"], projectile["y"], projectile["z"])
        gluSphere(quadric, 6, 8, 8)
        glPopMatrix()

def draw_first_person_weapon():
    if not game["first_person"]:
        return
    
    glMatrixMode(GL_PROJECTION)
    glPushMatrix()
    glLoadIdentity()
    gluPerspective(45, WIN_W/WIN_H, 0.1, 500)
    glMatrixMode(GL_MODELVIEW)
    glPushMatrix()
    glLoadIdentity()
    
    swing = max(0, game["attack_cooldown"])
    
    if game["current_weapon"] == "sword":
        glTranslatef(0.38, -0.38, -1)
        glRotatef(-15, 1, 0, 0)
        glRotatef(-8, 0, 1, 0)
        glRotatef(swing * 45, 1, 0, 0)
        
        quadric = gluNewQuadric()
        
        glColor3f(0.35, 0.20, 0.08)
        glPushMatrix()
        glTranslatef(0, 0, 0)
        gluCylinder(quadric, 0.025, 0.022, 0.18, 8, 3)
        glPopMatrix()
        
        glColor3f(0.70, 0.68, 0.30)
        glPushMatrix()
        glTranslatef(0, 0, 0.18)
        glScalef(0.02, 0.22, 0.02)
        glutSolidCube(1)
        glPopMatrix()
        
        glColor3f(0.82, 0.84, 0.92)
        glPushMatrix()
        glTranslatef(0, 0, 0.19)
        glScalef(0.015, 0.028, 0.58)
        glutSolidCube(1)
        glPopMatrix()
        
        glColor3f(0.60, 0.62, 0.72)
        glPushMatrix()
        glTranslatef(0.009, 0, 0.19)
        glScalef(0.003, 0.012, 0.54)
        glutSolidCube(1)
        glPopMatrix()
    else:
        glTranslatef(0.30, -0.32, -0.9)
        glRotatef(-10, 1, 0, 0)
        glRotatef(-5, 0, 1, 0)
        glRotatef(swing * 15, 1, 0, 0)
        
        quadric = gluNewQuadric()
        
        glColor3f(0.48, 0.30, 0.12)
        glPushMatrix()
        glScalef(0.045, 0.055, 0.30)
        glutSolidCube(1)
        glPopMatrix()
        
        glColor3f(0.35, 0.20, 0.08)
        glPushMatrix()
        glTranslatef(0, -0.04, 0.05)
        glScalef(0.035, 0.05, 0.08)
        glutSolidCube(1)
        glPopMatrix()
        
        glColor3f(0.55, 0.35, 0.15)
        glPushMatrix()
        glTranslatef(0, 0.18, 0.16)
        glRotatef(8, 1, 0, 0)
        glScalef(0.018, 0.16, 0.018)
        glutSolidCube(1)
        glPopMatrix()
        
        glPushMatrix()
        glTranslatef(0, -0.18, 0.16)
        glRotatef(-8, 1, 0, 0)
        glScalef(0.018, 0.16, 0.018)
        glutSolidCube(1)
        glPopMatrix()
        
        glColor3f(0.90, 0.90, 0.85)
        glLineWidth(1.5)
        glBegin(GL_LINES)
        glVertex3f(0, 0.26, 0.16)
        glVertex3f(0, -0.26, 0.16)
        glEnd()
        glLineWidth(1)
        
        glColor3f(0.70, 0.70, 0.70)
        glPushMatrix()
        glTranslatef(0, 0, 0.20)
        gluCylinder(quadric, 0.006, 0.006, 0.16, 6, 2)
        glPopMatrix()
    
    glPopMatrix()
    glMatrixMode(GL_PROJECTION)
    glPopMatrix()
    glMatrixMode(GL_MODELVIEW)

def draw_minimap():
    if not game["show_minimap"]:
        return
    
    level_grid = game["grid"]
    rows = len(level_grid)
    cols = len(level_grid[0]) if rows else 0
    tile_size = 8
    padding = 10
    origin_x = WIN_W - cols * tile_size - padding
    origin_y_base = WIN_H - padding-30
    
    glMatrixMode(GL_PROJECTION)
    glPushMatrix()
    glLoadIdentity()
    gluOrtho2D(0, WIN_W, 0, WIN_H)
    glMatrixMode(GL_MODELVIEW)
    glPushMatrix()
    glLoadIdentity()
    glDisable(GL_DEPTH_TEST)
    
    glBegin(GL_QUADS)
    for row in range(rows):
        for col in range(cols):
            if (row, col) not in game["explored"]:
                continue
            
            tile_type = level_grid[row][col]
            pixel_x = origin_x + col * tile_size
            pixel_y = origin_y_base - (row + 1) * tile_size
            
            if tile_type == TILE_WALL:
                glColor3f(0.48, 0.43, 0.38)
            elif tile_type == TILE_EXIT:
                glColor3f(0, 1, 0.2)
            elif tile_type == TILE_DOOR:
                glColor3f(0.50, 0.25, 0)
            else:
                glColor3f(0.18, 0.16, 0.15)
            
            glVertex2f(pixel_x, pixel_y)
            glVertex2f(pixel_x + tile_size, pixel_y)
            glVertex2f(pixel_x + tile_size, pixel_y + tile_size)
            glVertex2f(pixel_x, pixel_y + tile_size)
    glEnd()
    
    player_row, player_col = world_to_cell(game["player_x"], game["player_y"])
    dot_x = origin_x + player_col * tile_size + tile_size // 2
    dot_y = origin_y_base - player_row * tile_size - tile_size // 2
    glColor3f(1, 1, 1)
    glPointSize(6)
    glBegin(GL_POINTS)
    glVertex2f(dot_x, dot_y)
    glEnd()
    
    glColor3f(1, 0.1, 0.1)
    glPointSize(5)
    glBegin(GL_POINTS)
    for enemy in game["enemies"]:
        if not enemy["alive"]:
            continue
        enemy_row, enemy_col = world_to_cell(enemy["x"], enemy["y"])
        if (enemy_row, enemy_col) in game["explored"]:
            enemy_dot_x = origin_x + enemy_col * tile_size + tile_size // 2
            enemy_dot_y = origin_y_base - enemy_row * tile_size - tile_size // 2
            glVertex2f(enemy_dot_x, enemy_dot_y)
    glEnd()
    glPointSize(1)
    
    glEnable(GL_DEPTH_TEST)
    glPopMatrix()
    glMatrixMode(GL_PROJECTION)
    glPopMatrix()
    glMatrixMode(GL_MODELVIEW)

def draw_hud():
    global damage_flash
    
    if damage_flash > 0:
        glMatrixMode(GL_PROJECTION)
        glPushMatrix()
        glLoadIdentity()
        gluOrtho2D(0, WIN_W, 0, WIN_H)
        glMatrixMode(GL_MODELVIEW)
        glPushMatrix()
        glLoadIdentity()
        glDisable(GL_DEPTH_TEST)
        glColor3f(0.80, 0, 0)
        border = 28
        glBegin(GL_QUADS)
        glVertex2f(0, WIN_H-border)
        glVertex2f(WIN_W, WIN_H-border)
        glVertex2f(WIN_W, WIN_H)
        glVertex2f(0, WIN_H)
        glVertex2f(0, 0)
        glVertex2f(WIN_W, 0)
        glVertex2f(WIN_W, border)
        glVertex2f(0, border)
        glVertex2f(0, 0)
        glVertex2f(border, 0)
        glVertex2f(border, WIN_H)
        glVertex2f(0, WIN_H)
        glVertex2f(WIN_W-border, 0)
        glVertex2f(WIN_W, 0)
        glVertex2f(WIN_W, WIN_H)
        glVertex2f(WIN_W-border, WIN_H)
        glEnd()
        glEnable(GL_DEPTH_TEST)
        glPopMatrix()
        glMatrixMode(GL_PROJECTION)
        glPopMatrix()
        glMatrixMode(GL_MODELVIEW)
    
    draw_tablet_bar(10, WIN_H - 55, 160, 16,
                    game["health"] / game["max_health"],
                    (0.88, 0.12, 0.12), (0.22, 0.22, 0.22))
    
    draw_rectangle_bar(10, WIN_H - 82, 160, 10,
                       game["stamina"] / game["max_stamina"],
                       (0.20, 0.45, 0.90))
    
    draw_text(10, WIN_H - 35, f"HP  {game['health']}/{game['max_health']}")
    draw_text(10, WIN_H - 70, f"STA {int(game['stamina'])}/{int(game['max_stamina'])}")
    draw_text(10, WIN_H - 102, f"Weapon : {game['current_weapon'].upper()}")
    draw_text(10, WIN_H - 130, f"Keys   : {game['inventory'].count(ITEM_KEY)}")
    draw_text(10, WIN_H - 160, f"Level  : {game['level']}")
    
    if game["first_person"]:
        cross_x, cross_y = WIN_W//2, WIN_H//2
        glMatrixMode(GL_PROJECTION)
        glPushMatrix()
        glLoadIdentity()
        gluOrtho2D(0, WIN_W, 0, WIN_H)
        glMatrixMode(GL_MODELVIEW)
        glPushMatrix()
        glLoadIdentity()
        glDisable(GL_DEPTH_TEST)
        glColor3f(1, 1, 1)
        glLineWidth(1.5)
        glBegin(GL_LINES)
        glVertex2f(cross_x-10, cross_y)
        glVertex2f(cross_x+10, cross_y)
        glVertex2f(cross_x, cross_y-10)
        glVertex2f(cross_x, cross_y+10)
        glEnd()
        glLineWidth(1)
        glEnable(GL_DEPTH_TEST)
        glPopMatrix()
        glMatrixMode(GL_PROJECTION)
        glPopMatrix()
        glMatrixMode(GL_MODELVIEW)

def draw_tablet_bar(x, y, width, height, fill_ratio, fill_color, bg_color):
    glMatrixMode(GL_PROJECTION)
    glPushMatrix()
    glLoadIdentity()
    gluOrtho2D(0, WIN_W, 0, WIN_H)
    glMatrixMode(GL_MODELVIEW)
    glPushMatrix()
    glLoadIdentity()
    glDisable(GL_DEPTH_TEST)
    
    radius = height / 2
    center_x = x + radius
    center_y = y + radius
    right_center_x = x + width - radius
    
    glColor3f(*bg_color)
    draw_capsule_fill(x, y, width, height, radius)
    
    fill_width = max(0, (width - 2*radius) * fill_ratio)
    glColor3f(*fill_color)
    
    if fill_ratio > 0:
        draw_half_circle(center_x, center_y, radius, 90, 270)
    
    if fill_width > 0:
        glBegin(GL_QUADS)
        glVertex2f(center_x, y)
        glVertex2f(center_x + fill_width, y)
        glVertex2f(center_x + fill_width, y + height)
        glVertex2f(center_x, y + height)
        glEnd()
    
    if fill_ratio >= 1:
        draw_half_circle(right_center_x, center_y, radius, -90, 90)
    
    glColor3f(0.8, 0.8, 0.8)
    glLineWidth(1.2)
    draw_capsule_outline(x, y, width, height, radius)
    glLineWidth(1)
    
    glEnable(GL_DEPTH_TEST)
    glPopMatrix()
    glMatrixMode(GL_PROJECTION)
    glPopMatrix()
    glMatrixMode(GL_MODELVIEW)

def draw_capsule_fill(x, y, width, height, radius):
    center_x = x + radius
    center_y = y + radius
    right_center_x = x + width - radius
    
    draw_half_circle(center_x, center_y, radius, 90, 270)
    
    glBegin(GL_QUADS)
    glVertex2f(center_x, y)
    glVertex2f(right_center_x, y)
    glVertex2f(right_center_x, y + height)
    glVertex2f(center_x, y + height)
    glEnd()
    
    draw_half_circle(right_center_x, center_y, radius, -90, 90)

def draw_half_circle(center_x, center_y, radius, start_angle, end_angle):
    segments = 12
    glBegin(GL_TRIANGLE_FAN)
    glVertex2f(center_x, center_y)
    for i in range(segments + 1):
        angle = math.radians(start_angle + (end_angle - start_angle) * i / segments)
        glVertex2f(center_x + radius * math.cos(angle), center_y + radius * math.sin(angle))
    glEnd()

def draw_capsule_outline(x, y, width, height, radius):
    center_x = x + radius
    center_y = y + radius
    right_center_x = x + width - radius
    segments = 12
    
    glBegin(GL_LINE_LOOP)
    for i in range(segments + 1):
        angle = math.radians(90 + 180 * i / segments)
        glVertex2f(center_x + radius * math.cos(angle), center_y + radius * math.sin(angle))
    for i in range(segments + 1):
        angle = math.radians(-90 + 180 * i / segments)
        glVertex2f(right_center_x + radius * math.cos(angle), center_y + radius * math.sin(angle))
    glEnd()

def draw_rectangle_bar(x, y, width, height, fill_ratio, color):
    glMatrixMode(GL_PROJECTION)
    glPushMatrix()
    glLoadIdentity()
    gluOrtho2D(0, WIN_W, 0, WIN_H)
    glMatrixMode(GL_MODELVIEW)
    glPushMatrix()
    glLoadIdentity()
    glDisable(GL_DEPTH_TEST)
    
    glColor3f(0.18, 0.18, 0.18)
    glBegin(GL_QUADS)
    glVertex2f(x, y)
    glVertex2f(x + width, y)
    glVertex2f(x + width, y + height)
    glVertex2f(x, y + height)
    glEnd()
    
    glColor3f(*color)
    glBegin(GL_QUADS)
    glVertex2f(x, y)
    glVertex2f(x + width * fill_ratio, y)
    glVertex2f(x + width * fill_ratio, y + height)
    glVertex2f(x, y + height)
    glEnd()
    
    glEnable(GL_DEPTH_TEST)
    glPopMatrix()
    glMatrixMode(GL_PROJECTION)
    glPopMatrix()
    glMatrixMode(GL_MODELVIEW)

def draw_text(x, y, text, font=GLUT_BITMAP_HELVETICA_18, color=(1,1,1)):
    glColor3f(*color)
    glMatrixMode(GL_PROJECTION)
    glPushMatrix()
    glLoadIdentity()
    gluOrtho2D(0, WIN_W, 0, WIN_H)
    glMatrixMode(GL_MODELVIEW)
    glPushMatrix()
    glLoadIdentity()
    glRasterPos2f(x, y)
    for character in text:
        glutBitmapCharacter(font, ord(character))
    glPopMatrix()
    glMatrixMode(GL_PROJECTION)
    glPopMatrix()
    glMatrixMode(GL_MODELVIEW)

def draw_game_over():
    glMatrixMode(GL_PROJECTION)
    glPushMatrix()
    glLoadIdentity()
    gluOrtho2D(0, WIN_W, 0, WIN_H)
    glMatrixMode(GL_MODELVIEW)
    glPushMatrix()
    glLoadIdentity()
    glDisable(GL_DEPTH_TEST)
    
    glColor3f(0.04, 0.04, 0.04)
    glBegin(GL_QUADS)
    glVertex2f(WIN_W//2-240, WIN_H//2-65)
    glVertex2f(WIN_W//2+240, WIN_H//2-65)
    glVertex2f(WIN_W//2+240, WIN_H//2+65)
    glVertex2f(WIN_W//2-240, WIN_H//2+65)
    glEnd()
    
    if game["game_over"]:
        draw_text(WIN_W//2-105, WIN_H//2+22, "GAME  OVER", GLUT_BITMAP_TIMES_ROMAN_24, (1,0.1,0.1))
        draw_text(WIN_W//2-90, WIN_H//2-22, "Press R to Restart")
    else:
        draw_text(WIN_W//2-130, WIN_H//2+22, f"LEVEL {game['level']} COMPLETE!", GLUT_BITMAP_TIMES_ROMAN_24, (0.2,1,0.2))
        draw_text(WIN_W//2-110, WIN_H//2-22, "Press N for next level")
    
    glEnable(GL_DEPTH_TEST)
    glPopMatrix()
    glMatrixMode(GL_PROJECTION)
    glPopMatrix()
    glMatrixMode(GL_MODELVIEW)

def save_game_state():
    save_data = {
        "level": game["level"],
        "health": game["health"],
        "stamina": game["stamina"],
        "inventory": game["inventory"],
        "current_weapon": game["current_weapon"],
        "explored": list(game["explored"]),
        "player_x": game["player_x"],
        "player_y": game["player_y"],
        "yaw": game["yaw"],
    }
    
    try:
        with open(SAVE_FILE, "w") as save_file:
            json.dump(save_data, save_file, indent=2)
        print(f"[SAVE] Saved to {SAVE_FILE}")
    except Exception as error:
        print(f"[SAVE] Failed: {error}")

def load_game_state():
    if not os.path.exists(SAVE_FILE):
        print("[LOAD] No save file.")
        return
    
    try:
        with open(SAVE_FILE) as save_file:
            save_data = json.load(save_file)
        
        game["level"] = save_data["level"]
        game["health"] = save_data["health"]
        game["stamina"] = save_data["stamina"]
        game["inventory"] = save_data["inventory"]
        game["current_weapon"] = save_data["current_weapon"]
        load_level(game["level"])
        game["player_x"] = save_data["player_x"]
        game["player_y"] = save_data["player_y"]
        game["yaw"] = save_data["yaw"]
        game["explored"] = set(tuple(cell) for cell in save_data["explored"])
        print(f"[LOAD] Loaded level {game['level']}")
    except Exception as error:
        print(f"[LOAD] Failed: {error}")

def handle_keyboard(key, x, y):
    global sprint_active
    
    keys_pressed.add(key)
    
    if key == b'l':
        sprint_active = not sprint_active
    if key == b'e':
        player_interact()
    if key == b'\t':
        game["show_minimap"] = not game["show_minimap"]
    if key == b'r':
        load_level(game["level"])
        game["health"] = game["max_health"]
    if key == b'n' and game["victory"]:
        game["level"] += 1
        load_level(game["level"])
    if key == b'q':
        switch_weapon()
    if key == b'v':
        game["first_person"] = not game["first_person"]
    if key == b'\x1b':
        glutLeaveMainLoop()

def handle_keyboard_up(key, x, y):
    keys_pressed.discard(key)

def handle_special_key(key, x, y):
    if key == GLUT_KEY_F5:
        save_game_state()
    elif key == GLUT_KEY_F9:
        load_game_state()
    elif game["first_person"]:
        if key == GLUT_KEY_UP:
            game["pitch"] = min(60, game["pitch"] + 3)
        elif key == GLUT_KEY_DOWN:
            game["pitch"] = max(-60, game["pitch"] - 3)
        elif key == GLUT_KEY_LEFT:
            game["yaw"] += 3
        elif key == GLUT_KEY_RIGHT:
            game["yaw"] -= 3
    else:
        if key == GLUT_KEY_LEFT:
            game["camera_yaw"] -= 4
        elif key == GLUT_KEY_RIGHT:
            game["camera_yaw"] += 4
        elif key == GLUT_KEY_UP:
            game["camera_pitch"] = min(80, game["camera_pitch"] + 3)
        elif key == GLUT_KEY_DOWN:
            game["camera_pitch"] = max(5, game["camera_pitch"] - 3)

def handle_mouse(button, state, x, y):
    if button == GLUT_LEFT_BUTTON and state == GLUT_DOWN:
        player_attack()
    elif button == GLUT_RIGHT_BUTTON and state == GLUT_DOWN:
        switch_weapon()

def update_game():
    global last_frame_time, delta_time
    current_time = time.time()
    delta_time = min(current_time - last_frame_time, 0.05)
    last_frame_time = current_time
    
    if not game["game_over"] and not game["victory"]:
        update_player(delta_time)
        update_enemies(delta_time)
        update_projectiles(delta_time)
        update_items()
    
    glutPostRedisplay()

def render_scene():
    glClearColor(0, 0, 0, 1)
    glClear(GL_COLOR_BUFFER_BIT | GL_DEPTH_BUFFER_BIT)
    glEnable(GL_DEPTH_TEST)
    glViewport(0, 0, WIN_W, WIN_H)
    
    setup_camera()
    draw_dungeon()
    draw_items()
    draw_enemies()
    draw_projectiles()
    draw_player()
    draw_first_person_weapon()
    draw_hud()
    draw_minimap()
    
    if game["game_over"] or game["victory"]:
        draw_game_over()
    
    glutSwapBuffers()

def main():
    glutInit()
    glutInitDisplayMode(GLUT_DOUBLE | GLUT_RGB | GLUT_DEPTH)
    glutInitWindowSize(WIN_W, WIN_H)
    glutInitWindowPosition(100, 10)
    glutCreateWindow(b"3D Dungeon Escape")
    
    load_level(1)
    game["health"] = 100
    game["inventory"] = []
    
    glutDisplayFunc(render_scene)
    glutKeyboardFunc(handle_keyboard)
    glutKeyboardUpFunc(handle_keyboard_up)
    glutSpecialFunc(handle_special_key)
    glutMouseFunc(handle_mouse)
    glutIdleFunc(update_game)
    
    print("=" * 60)
    print("  3D DUNGEON ESCAPE  —  Controls")
    print("  W/S             → Move forward/backward")
    print("  A/D             → Rotate left/right")
    print("  L (Shift)       → Sprint toggle")
    print("  Arrow Keys      → Look around (1st) / Orbit cam (3rd)")
    print("  V               → Toggle 1st / 3rd person")
    print("  LClick          → Attack")
    print("  RClick / Q      → Switch weapon")
    print("  E               → Interact (door / lever)")
    print("  TAB             → Toggle minimap")
    print("  F5 / F9         → Save / Load")
    print("  R               → Restart level")
    print("  N               → Next level (after win)")
    print("  ESC             → Quit")
    print("=" * 60)
    
    glutMainLoop()

if __name__ == "__main__":
    main()
import pygame
import sys
sys.path.append('tools')
from zx_gfx import (font_sprite_names, font_sprite_data, sprite_names, sprite_data, get_font_sprite_data,
                    SPRITE_WIDTH, SPRITE_HEIGHT, draw_sprite, draw_font_sprite, sprite_at,
                    sprint, border, BLACK, BLUE, RED, MAGENTA, GREEN, CYAN, YELLOW, WHITE,
                    BRIGHT_BLUE, BRIGHT_RED, BRIGHT_MAGENTA, BRIGHT_GREEN, BRIGHT_CYAN, BRIGHT_YELLOW,
                    BRIGHT_WHITE, PALETTE, CURSOR_FRAME, CURSOR_FLY, CURSOR_CORNER, CURSOR_S, cursor_list)
from gamedata import (wizards, creature_list, creations, spell_list, animation_list, starting_position_data,
                    F_MOUNT, F_MOUNT_ANY, F_FLYING, F_UNDEAD, F_TREE, F_EXPIRES, F_EXPIRES_SPELL, F_NOCORPSE,
                    F_INVULN, F_STRUCT, F_ETH, F_ENGULFS, F_SPREADS, FLAGS, corpses, victims,
                    MIN_WIZARDS, MAX_WIZARDS, MAX_SPELLS)
from enum import Enum
import random, math
pygame.init()
pygame.mixer.init()

# TEST_SPELL = 36

# TODO: 'Bonus' engagement attack if ending movement engaged
# TODO: Allow ranged attackers to attack after successfully attacking and/or being mounted
# TODO: Finish flight
# TODO: spell failure
# TODO: finish sound
# TODO: Primitive AI: much like the original, lots of random
# TODO: AI: Describe game state through OpenAI API calls to fetch spell selections, spell casting and movement decisions from GPT-4 
# TODO: Fix creations dictlist to be more consistent with wizards dictlist
# TODO: Constants and file structure review
# TODO: Non-magic and non-undead ranged attacks should not kill undead
# TODO: Runtime window rescaling: UP/DOWN keys to change RESCALE_FACTOR and re-init window accordingly

# Constants for tile, arena and screen dimensions
CAPTION = 'Entro.py: Battle of Elderly Wizards'
TILE_SIZE = 16
ARENA_COLUMNS, ARENA_ROWS = 15, 10
ARENA_WIDTH, ARENA_HEIGHT = ARENA_COLUMNS * TILE_SIZE, ARENA_ROWS * TILE_SIZE
BORDER_WIDTH = TILE_SIZE
STATUS_LINE_HEIGHT = TILE_SIZE * 1.5
SCREEN_WIDTH = ARENA_WIDTH + 2 * BORDER_WIDTH
SCREEN_HEIGHT = ARENA_HEIGHT + BORDER_WIDTH + STATUS_LINE_HEIGHT

# The original resolution arena is rescaled
RESCALE_FACTOR = 6
RENDER_WIDTH,RENDER_HEIGHT = SCREEN_WIDTH * RESCALE_FACTOR, SCREEN_HEIGHT * RESCALE_FACTOR
X_SCALE, Y_SCALE = RENDER_WIDTH / SCREEN_WIDTH, RENDER_HEIGHT / SCREEN_HEIGHT

# Initialize the screen and game variables
GS_INTRO, GS_SETUP, GS_NAME, GS_MENU, GS_SELECT, GS_CAST, GS_ARENA, GS_INSPECT, GS_INFO, GS_INFO_ARENA, GS_GAME_OVER = range(11)  # Game states
main_screen = pygame.display.set_mode((RENDER_WIDTH, RENDER_HEIGHT))
pygame.display.set_caption(CAPTION)
screen = pygame.Surface((SCREEN_WIDTH, SCREEN_HEIGHT))  # This is where we'll render everything initially
clock = pygame.time.Clock()
start_time = pygame.time.get_ticks()

cursor_pos = [0, 0]         # Using a mutable list to manage cursor tile position changes on the arena
cursor_type = CURSOR_S
selection = None            # Current wizard's arena selection
illusion_checking = False   # We're asking whether wizard wants this next creation to be an illusion
dismount_checking = False   # We're asking a mounted wizard whether they want to attempt to dismount
rangedCombatTime = False    # A ranged combat equipped object just completed its move and should select a target for ranged attack
animations = []
moves_remaining = 0
num_wizards = 2
messageText = ""
current_screen = GS_INTRO
current_wizard = 0 # Used to progress through setup and turns
worldAlignment = 0
newCreations = []
showBases = True
highlightWizard = 0
turn = 1

SOUND_SET = [pygame.mixer.Sound('sound/S60-key_bloop.mp3'), pygame.mixer.Sound('sound/S10-tick.mp3'), 
            pygame.mixer.Sound('sound/spell_success.mp3'), pygame.mixer.Sound('sound/engaged.mp3'),
            pygame.mixer.Sound('sound/sound_effect_22-undead.mp3'), pygame.mixer.Sound('sound/sound_effect_11-walk.mp3'),
            pygame.mixer.Sound('sound/sound_effect_21-selected.mp3'), pygame.mixer.Sound('sound/sound_effect_16-explosion.mp3')]
SND_KEY, SND_TICK, SND_SUCCESS, SND_ENGAGED, SND_UNDEAD, SND_WALK, SND_SELECTED, SND_EXPLOSION = SOUND_SET[:8]
sound_channels = {}
sounds = []

def play_sound():
    global sounds, sound_channels
    if sounds and len(animations) % 2 == 0: sound = sounds.pop() # The animations check ensures that sounds don't get too out of sync with animations
    else: return
    # Check if the sound is already playing
    if sound in sound_channels and sound_channels[sound].get_busy():
        while sound_channels[sound].get_busy():
            pygame.time.wait(50)  # Wait for 50 milliseconds before checking again
        sound_channels[sound].play(sound)
    else:
        # Find an available channel and play the sound
        channel = pygame.mixer.find_channel(True)
        if channel:
            channel.play(sound)
            sound_channels[sound] = channel
        else:
            print("No available channel to play sound.")

def check_engagement(activeObject):
    global wizards, creations, messageText, sounds
    alreadyEngaged = activeObject['engaged']
    neighbours = get_all_neighbours(wizards + creations, activeObject['x'], activeObject['y'])
    manoeuvre_rating = activeObject['manvr'] if is_wizard(activeObject) else activeObject['data']['mnv']
    # print(f"AP: {activeObject}")
    for neighbour in neighbours:
        if activeObject['owner'] == neighbour['owner']:
            # print(f"Friendlies don't cause engagements ({neighbour['name']})")
            continue
        if string_in_object(neighbour, F_STRUCT) or string_in_object(neighbour, F_SPREADS) or string_in_object(neighbour, F_EXPIRES_SPELL):
            # print("Structures and spreaders don't cause engagements")
            continue
                
        roll = random.randint(0,9)
        print(f"{activeObject['name']} ({activeObject['owner']}) with MR: {manoeuvre_rating} rolled {roll}   trigger: {neighbour['name']} ({neighbour['owner']}) at {neighbour['x']},{neighbour['y']}")        

        if roll < manoeuvre_rating and (activeObject['owner'] != neighbour['owner']):
            messageText = "ENGAGED TO ENEMY"
            sounds.append(SND_ENGAGED)
            # print(f"Result: True")
            return True

    # print( f"Neighbours: {[d['name'] for d in neighbours]}" )
    # print(f"Result: no change\n")
    return alreadyEngaged

def check_los(originObject, x1, y1):
    """ This uses the Bresenham line algorithm to incrementally check each grid cell from (x0,y0) to (x1,y1). 
        If any blocked cell is encountered, it returns False. Otherwise it returns True if LoS is clear.
    """
    x0,y0 = originObject['x'], originObject['y']

    dx = abs(x1 - x0)
    dy = abs(y1 - y0)
    
    if dx + dy == 0: return True # No obstacles at no distance

    sx = -1 if x0 > x1 else 1
    sy = -1 if y0 > y1 else 1

    if dx > dy:
        err = dx / 2.0
        x = x0 + sx
        while x != x1:
            if get_obstruction(x, y0, originObject, ignoreEthereals=True):
                return False
            err -= dy
            if err < 0:
                y0 += sy
                err += dx
            x += sx
    else:
        err = dy / 2.0
        y = y0 + sy
        while y != y1:
            if get_obstruction(x0, y, originObject, ignoreEthereals=True):
                return False
            err -= dx
            if err < 0:
                x0 += sx
                err += dy
            y += sy
    return True

def get_spiral_ring(radius):
    """ This oddly specific spiral pattern is just an attempt to more authentically
        replicate the behaviour of the original Z80 code where it made more sense.   """
    coords = []

    def add(x, y):
        # if minWidth <= x <= widthLimit and minHeight <= y <= heightLimit and (x, y) not in coords:
        coords.append((a, b))

    a,b = 0, radius
    while a > 0 - radius:
        add(a, b)
        a -= 1   
    while b > 0 - radius: # Left edge
        add(a, b)
        b -= 1
    while a < radius: # Top row left to right
        add(a, b)
        a += 1
    while b < radius: # Right edge
        add (a, b)
        b += 1
    while a > 0: # Closing section of bottom if necessary
        add(a, b)
        a -= 1

    # return coords as a list of mutable lists instead of a list of tuples
    return [list(coord_tuple) for coord_tuple in coords]

def get_all_neighbours(list_of_dicts: list, x0: int, y0: int, n: int = 1, ring: bool = True):
    neighbours = []

    for item in list_of_dicts:
        chebyshev_distance = max(abs(item['x'] - x0), abs(item['y'] - y0))
        
        if ring:
            # Include if Chebyshev distance is exactly 'n'
            if chebyshev_distance == n:
                neighbours.append(item)
        else:
            # Include if within 'n' Chebyshev distance
            if chebyshev_distance <= n:
                neighbours.append(item)

    return neighbours

def get_random_neighbour_location(x, y, grid_width, grid_height):
    # Generate the set of valid neighbouring coordinates
    neighbours = [(x + dx, y + dy) for dx, dy in [(-1, 0), (1, 0), (0, -1), (0, 1)]
                if 0 <= x + dx < grid_width and 0 <= y + dy < grid_height]
    # Return a random neighbour
    return random.choice(neighbours)

def spread_spreaders():
    global creations, victims

    for creation in creations:
        # We use 'has_moved' flag to indicate freshly created elements shouldn't replicate in the same turn
        if  F_SPREADS in creation['data']['status'] and not creation['has_moved']:
            print(f"found a spreader at {creation['x']},{creation['y']}")

            if random.randint(1, 10) <= 9: # 90% chance of spreading
                # Spreading
                (newX, newY) = get_random_neighbour_location(creation['x'], creation['y'], ARENA_COLUMNS, ARENA_ROWS)

                victim = get_obstruction(newX, newY)
                if victim:

                    if not is_wizard(victim): # Some things can't be burned or engulfed but wizards aren't one of them
                        if any(s in victim['data']['status'] for s in [F_SPREADS, F_STRUCT, F_TREE]): continue 
                    
                    # Different spreaders behave differently
                    if (F_ENGULFS not in creation['data']['status']):
                        # Lethal spreader e.g. fire
                        rider = get_rider(victim)
                        if rider: kill(rider) 
                        else: kill(victim)
                        # Fire clears corpses too:
                        for corpse in corpses:
                            if corpse['x'] == newX and corpse['y'] == newY: corpses.remove(corpse)

                        continue # to next element
                    else:
                        # Non-lethal spreader e.g. Blobs, which avoid wizards and mounted mounts
                        if (is_wizard(victim) or get_rider(victim)):
                            # This blob will not engulf this wizard, whether on foot mounted
                            continue
                        else:
                            # Everything else, except the permanent exclusions, gets gobbled
                            victims.append(victim)
                            kill_creation(victim) # Not really killed, just buried 
                            print(f"{victim['name']} overwhelmed by {creation['name']}")

                # Victim or not, we are still creating a new element
                print(f"New {creation['name']} at {newX},{newY}")
                create_creation(creation['name'], creation['owner'], newX, newY, False, True)

            if random.randint(1,10) <= 1: # Also 10% chance of disappearing
                print(f"{creation['name']} expires")
                kill_creation(creation, False)
                # Liberate blob victim
                for victim in victims:
                    if (creation['x'], creation['y']) == (victim['x'], victim['y']): 
                        print(f"{victim['name']} liberated!")
                        creations.append(victim)
                        victims.remove(victim)

    # We've done spreaders.  We'll squeeze expirations in here too
    run_expirations()

    return

def run_expirations():
    """ Checking magic trees and castles for expiration """
    # Loop through creations looking for F_EXPIRES and F_EXPIRES_SPELL flags
    for creation in creations:
        if F_EXPIRES in creation['data']['status']:
            if random.randint(1,10) <= 2: # 20% chance of disappearing

                if F_EXPIRES_SPELL in creation['data']['status']:
                    for wizard in wizards:
                        if wizard['x'] == creation['x'] and wizard['y'] == creation['y'] and wizard['mounted']:
                            print(f"{wizard['name']} has {len(wizard['spell_book'])} spells")
                            if len(wizard['spell_book']) < MAX_SPELLS:
                                wizard['spell_book'].append(random.choice(spell_list[2:][:-1]))
                                messageText = f"NEW SPELL FOR {wizard['name']} ({wizard['spell_book'][-1]['spell_name']})"
                                print(messageText)
                            else: print('spell blocked')
                            print(f"{creation['name']} expires")
                            kill_creation(creation, False)
                            break
                else:
                    print(f"{creation['name']} expires")
                    kill_creation(creation, False, True)

def get_world_alignment_string():
    global worldAlignment
    if worldAlignment > 0: return f"(LAW {'↥' * (worldAlignment - 1)})"
    elif worldAlignment < 0: return f"(CHAOS {'*' * (abs(worldAlignment) - 1)})"
    else: return ""

def get_sprite_info(name):
    global animation_list
    # Convert the name parameter to lowercase and replace spaces with underscores to match the format
    name = name.replace(' ', '_').lower()
    # Search for the matching animation by name
    for animation in animation_list:
        if animation['name'] == name:
            # Return the sprites list if the name matches
            return animation['sprites']
    # Return an empty list if no match is found
    return []

def clean_label(label):
    return label.replace('_',' ').title()

def have_same_sign(a, b):
    return (a > 0 and b > 0) or (a < 0 and b < 0) or (a == 0 and b == 0)

def get_alignment_character(ChaosValue: int) -> str:
    if ChaosValue>0:return '↥'
    elif ChaosValue==0:return '-'
    return '*'

def get_casting_chance(wizard: int, pos: int):
    global worldAlignment
    if worldAlignment == 0: chance = wizards[wizard]['spell_book'][pos]['chance']
    elif have_same_sign(worldAlignment, wizards[wizard]['spell_book'][pos]['law']):
        # Alignment boost for spells aligned with the world
        chance = wizards[wizard]['spell_book'][pos]['chance'] + (abs(worldAlignment) // 4)
        # print(f"chance: {chance * 10}%  World Alignment: {worldAlignment}  Spell Alignment: {wizards[wizard]['spell_book'][pos]['law']})")
    else:
        # World alignment will not help with this spell 
        chance = wizards[wizard]['spell_book'][pos]['chance']
    
    # Add wizard's ability and clamp 0-9
    chance = max(0, min(chance + wizards[wizard]['ability'], 9))
    return chance + 1

def get_chance_color(chance: int):
    return PALETTE[2 + (chance // 2)]

def unpack_coordinates(sequential_position, num_columns=16, num_rows=10) -> tuple:
    """
    Convert a sequential position number to x, y coordinates in a 16x10 arena.

    Parameters:
    - sequential_position: The sequential position (0-indexed)
    - num_columns: The number of columns in the arena
    - num_rows: The number of rows in the arena

    Returns:
    - A tuple of (x, y) coordinates
    """

    # if sequential_position < 0 or sequential_position >= num_columns * num_rows:
    #     raise ValueError("Sequential position is out of bounds for the arena size")

    x = sequential_position % num_columns
    y = sequential_position // num_columns

    return x, y

def nextWizard():
    global wizards, current_wizard, num_wizards, cursor_pos, cursor_type, current_screen, messageText, turn
    if current_wizard == num_wizards:
        # New round
        current_wizard = 1
        if current_screen == GS_ARENA: turn += 1
    else: current_wizard += 1
    
    if current_screen == GS_CAST: 
        if wizards[current_wizard]['selected']: 
            messageText = clean_label(wizards[current_wizard]['selected']['label'])
            cursor_type = CURSOR_S
        cursor_pos = [ wizards[current_wizard]['x'], wizards[current_wizard]['y'] ]
        messageText = f"{wizards[current_wizard]['name']}"
        if wizards[current_wizard]['selected']: messageText +=  f"  {clean_label(wizards[current_wizard]['selected']['label'])}" + (f" {wizards[current_wizard]['selected']['distance']}" if wizards[current_wizard]['selected']['distance'] > 0 else "") + (f" ({wizards[current_wizard]['multicast']})" if wizards[current_wizard]['multicast'] > 1 else "") # spell label or blank

    elif current_screen == GS_ARENA:
        cursor_type = CURSOR_FRAME
        cursor_pos = [ wizards[current_wizard]['x'], wizards[current_wizard]['y'] ]
        messageText = f"{wizards[current_wizard]['name']}'s turn"

    print(f"turn: {turn}    current_screen: {current_screen}    current_wizard: {current_wizard}   ")
    return

    if current_screen == GS_CAST:
        if wizards[current_wizard]['selected']: 
            messageText = clean_label(wizards[current_wizard]['selected']['label'])
            cursor_type = CURSOR_S

def prepare_wizards():
    global wizards, num_wizards
    this_wizard = 1
    while this_wizard <= num_wizards:
        compar = wizards[this_wizard]['level'] # Variable name taken from original assembler label
        wizards[this_wizard]['combat'] = (random.randint(0, 9) // 2) + 1 + (compar // 2)
        wizards[this_wizard]['defense'] = (random.randint(0, 9) // 2) + 1 + (compar // 2)
        wizards[this_wizard]['manvr'] = (random.randint(0, 9) // 2) + 3 + (compar // 4)
        wizards[this_wizard]['magic resistance'] = (random.randint(0, 9) // 4) + 6 
        wizards[this_wizard]['ability'] = (compar // 2) + random.randint(0, 1)
        wizards[this_wizard]['defeated'] = False
        # All wizards:    
        wizards[this_wizard]['spell_book'] = [spell_list[0],spell_list[1]] # Everyone gets Disbelieve and Meditate

        try:
            if TEST_SPELL: wizards[this_wizard]['spell_book'] += [spell_list[TEST_SPELL]] # Everyone gets the test spell
        except:
            print("No test spell has been set")
        wizards[this_wizard]['spell_book'] += [random.choice(spell_list[2:][:-1]) for _ in range( min(20,(random.randint(0,9) // 2) + 10 + compar // 2) )]
        
        this_wizard += 1    

def prepare_starting_positions():
    global wizards, num_wizards
    positions = starting_position_data[num_wizards - 2] # Starting positions table rows start with 2 players
    # print(positions)
    for i, position in enumerate(positions):
        wizards[i + 1]['x'], wizards[i + 1]['y'] = unpack_coordinates(position + 17, ARENA_COLUMNS + 1)
        # print(f"{wizards[i+1]['name']} starts at {wizards[i+1]['x']},{wizards[i+1]['y']}")

def get_creature_frames(creatureName: str):
    global animation_list
    for creature in animation_list:
        if creature['name'] == creatureName: return creature['frames']

def get_distance(point1: list, point2: list) -> float:
    """ Not using Manhattan, Chebyshev or Pythagorean. Nope.
        We're using my take on the Gollop algorithm.         """

    x0, y0 = point1
    x1, y1 = point2

    # Calculate horizontal and vertical distances
    dx = abs(x1 - x0)
    dy = abs(y1 - y0)

    # Determine the number of diagonal moves
    diagonal_moves = min(dx, dy)

    # Calculate the remaining straight moves
    straight_moves = abs(dx - dy)

    # Sum up the distances
    gollop_distance = math.floor(diagonal_moves * 1.5 + straight_moves)
    return gollop_distance

def get_collisions(list_of_dicts, x, y):
    # Return a list of collisions at these coordinates
    matching_items = [d for d in list_of_dicts if d.get('x') == x and d.get('y') == y]
    return matching_items

def select_at(x,y, includeCorpses: bool = False):
    # Returns a single collision for selection or targeting
    objectList = wizards + creations
    if includeCorpses: objectList += corpses
    potential_selections = get_collisions(objectList, cursor_pos[0], cursor_pos[1])
    # potential_selections = get_all_collisions(cursor_pos[0], cursor_pos[1], includeCorpses)
    if potential_selections:
        selection = potential_selections[-1] 
    else: 
        selection = None
    return(selection)

def get_obstruction(x, y, ignoreSubject=None, ignoreEthereals: bool = False):
    # Returns single object from wizards and creations, optionally ignoring the subject and/or ethereal creatures
    if ignoreEthereals:
        matching_items = [d for d in creations 
                          if d['x'] == x and d['y'] == y 
                          and d != ignoreSubject 
                          and not d.get('mounted')
                          and not F_ETH in d['data']['status']]
        matching_items += [d for d in wizards 
                          if d['x'] == x and d['y'] == y 
                          and d != ignoreSubject 
                          and not d.get('mounted')]
    else:
        matching_items = [d for d in wizards + creations 
                          if d['x'] == x and d['y'] == y 
                          and d != ignoreSubject 
                          and not d.get('mounted')]

    if matching_items: 
        return matching_items[0]

    return None

def remove_spell(wizard: int, spell_name: str):
    for spell in wizards[wizard]['spell_book']:
        if spell.get('spell_name') == spell_name:
            wizards[wizard]['spell_book'].remove(spell)
            break  # Return early if the item is found and removed

def create_creation(creatureName: str, owner: int, x: int, y: int, illusion: bool = False, hasMoved: bool = True):
    """ Note that creations are shifted from newCreations to Creations during the draw_animations() call """
    global newCreations

    data = get_creature_stats(creatureName)

    newCreations += [
    {'name': creatureName,
    'owner': owner,
    'frame_set': get_creature_frames(creatureName),
    'x': x, 
    'y': y,
    'illusion': illusion,
    'has_moved': hasMoved,
    'engaged': False,
    'disbelieved': False, 
    'data': data}]
    return

def kill_creation(target, generateCorpse: bool = True, forceInvulnerableDestruction: bool = False):
    global creations, corpses
    for creation in creations:
        if target == creation:
            if (F_INVULN not in creation['data']['status']) or forceInvulnerableDestruction: 
                if F_MOUNT in creation['data']['status'] or F_MOUNT_ANY in creation['data']['status']:
                    mounted_wizards = [d for d in wizards if d['x'] == target['x'] and d['y'] == target['y'] and d['mounted']]
                    if mounted_wizards:
                        mounted_wizards[0]['mounted'] = False

                if generateCorpse and (F_NOCORPSE not in creation['data']['status']):
                    print(f"Corpse appeared at {creation['x']},{creation['y']}")
                    corpses.append(creation)

                creations.remove(creation)

                return True

    return False 

def kill_wizards_creations(thisWizard: int):
    global creations
    for creation in creations:
        if creation['owner'] == thisWizard:
            animations.append({'title': 'woop', 'rate': 30, 'x': creation['x'], 'y': creation['y'], 'frame_set': [("woop" + str(i), PALETTE[wizards[thisWizard]['palette']]) for i in range(1,10)], 'destination': None})
            
            if F_MOUNT_ANY in creation['data']['status'] or F_MOUNT in creation['data']['status']:
                if get_rider(creation):
                    dismount(thisWizard, creation['x'], creation['y'])
            creations.remove(creation)
    return

def kill_wizard(thisWizard: int):
    global wizards, current_screen
    print(f"Wizard {wizards[thisWizard]['name']} dying! 'x': {wizards[thisWizard]['x']}, 'y': {wizards[thisWizard]['y']}")
    animations.append({'title': 'woop', 'rate': 30, 'x': wizards[thisWizard]['x'], 'y': wizards[thisWizard]['y'], 'frame_set': [("woop" + str(i), PALETTE[wizards[thisWizard]['palette']]) for i in range(1,10)], 'destination': None})
    kill_wizards_creations(thisWizard)
    wizards[thisWizard]['defeated'] = True
    wizards[thisWizard]['mounted'] = True # Also ensures no attempt to draw them in arena
    wizards[thisWizard]['x'], wizards[thisWizard]['y'] = 255, 255
    
    # Game Over check:
    survivors = len([w for w in wizards if w['defeated'] is False])
    print(f"Survivors: {survivors} out of {num_wizards}")
    if survivors == 1:
        # Victory!
        current_screen = GS_GAME_OVER
        print(f"Victory for {[w['name'] for w in wizards if w['defeated'] is False]}!")

    return True

def kill(target, generateCorpse: bool = True):
    """ Kills either a wizard or a creation """
    return kill_wizard(target['owner']) if is_wizard(target) else kill_creation(target, generateCorpse)

def attack(target, attack_stat: int, magical: bool = False):
    global creations, wizards
    if is_wizard(target): # Target is a wizard!
        defence = target['magicRes'] if magical else target['defence']
    else: # Target is a creation
        defence = target['data']['res'] if magical else target['data']['def']

    attack_roll = attack_stat + random.randint(0,6)
    defence_roll = defence + random.randint(0,6)
    print(f"[{target['name']} attacked]   Attacker: {attack_roll}({attack_stat})   Defender: {defence_roll}({defence})   Result: {('Succeeds' if attack_roll >= defence_roll else 'Fails')}")
    sounds.append(SND_ATTACK)
    return True if attack_roll >= defence_roll else False

def melee_attack(target, attack_stat: int, magical: bool = False):
    global creations, wizards
    animations.append({'title': 'attack', 'rate': 20, 'x': target['x'], 'y': target['y'], 'frame_set': [("attack" + str(i), BRIGHT_CYAN) for i in range(1,5)], 'destination': None})
    success = attack(target, attack_stat, magical)
    if success:
        if kill(target): 
            print(f"{target['name']} destroyed")
            return True
    return False

def string_in_object(dicts, target: str):
    """
    Recursively checks if a target string is present in a list of dictionaries, including nested dictionaries and lists.

    Args:
    dicts (list): A list of dictionaries (or lists) to search through.
    target (str): The string to search for.

    Returns:
    bool: True if the target string is found, False otherwise.

    This function iterates through each element in the list `dicts`. If an element is a dictionary, it checks each of its values.
    If the value is the target string, it returns True. If the value is another list or dictionary, it calls itself recursively on that value.
    If an element is a list, the function calls itself recursively on that list.
    """
    if isinstance(dicts, dict):
        for value in dicts.values():
            if target == value or string_in_object(value, target):
                return True
    elif isinstance(dicts, list):
        for item in dicts:
            if target == item or string_in_object(item, target):
                return True
    return False

def adjacent_tree_check(x,y):
    neighbours = get_all_neighbours(creations + newCreations, x, y)

    if string_in_object(neighbours, F_TREE):
        return True
    return False

def cast_attempt():
    buffs = ['magic_sword_spell', 'magic_knife_spell', 'magic_armour_spell', 'magic_shield_spell', 'magic_wings_spell', 'magic_bow_spell']
    global cursor_pos, wizards, current_wizard, creations, messageText, animations, worldAlignment, selection, sounds

    def spell_succeeds(count: int = 1):
        global wizards, worldAlignment
        worldAlignment += wizards[current_wizard]['selected']['law']
        remove_spell(current_wizard, wizards[current_wizard]['selected']['spell_name'])
        messageText = "SPELL SUCCEEDS"
        wizards[current_wizard]['multicast'] = 0
        wizards[current_wizard]['selected'] = None
        for i in range(0, count): 
            sounds.append(SND_SUCCESS)
        return

    def spell_fails():
        remove_spell(current_wizard, wizards[current_wizard]['selected']['spell_name'])
        messageText = "SPELL FAILS"
        wizards[current_wizard]['selected'] = None
        return

    # Range check
    distance = get_distance( [wizards[current_wizard]['x'], wizards[current_wizard]['y']], cursor_pos )
    print(f"Distance: {distance}   Limit: {wizards[current_wizard]['selected']['distance']}")
    if (distance > wizards[current_wizard]['selected']['distance']) and wizards[current_wizard]['selected']['distance'] != 0:
        messageText = "OUT OF RANGE"
        return False

    # Line of Sight check; note exemptions
    if 'dark_power_spell' not in wizards[current_wizard]['selected']['spell_name'] and wizards[current_wizard]['selected']['spell_name'] != 'disbelieve':
        if not check_los(wizards[current_wizard], cursor_pos[0], cursor_pos[1]):
            messageText = "NO LINE OF SIGHT"
            return False

    if 'disbelieve' in wizards[current_wizard]['selected']['spell_name']:
        animations.append({'title': 'beam', 'rate': 10, 'x': wizards[current_wizard]['x'], 'y': wizards[current_wizard]['y'], 'dest_x': cursor_pos[0], 'dest_y': cursor_pos[1], 'colour': BRIGHT_WHITE})
        collisions = get_collisions(creations, cursor_pos[0], cursor_pos[1])
        if collisions:
            if collisions[0]['illusion']:
                # print(f"Illusion to be destroyed! ({collisions[0]['name']})")
                kill_creation(collisions[0], False)
                animations.append({'title': 'explosion', 'rate': 30, 'x': cursor_pos[0], 'y': cursor_pos[1], 'frame_set': [("explosion" + str(i), PALETTE[random.randint(1,7)]) for i in range(0,7)], 'destination': None})
                sounds.append(SND_EXPLOSION)

                spell_succeeds(0)
            animations.append({'title': 'attack', 'rate': 20, 'x': cursor_pos[0], 'y': cursor_pos[1], 'frame_set': [("attack" + str(i), PALETTE[random.randint(1,7)]) for i in range(1,5)], 'destination': None})

        messageText = "SPELL FAILS"
        wizards[current_wizard]['selected'] = None
        return True

    elif 'meditate' in wizards[current_wizard]['selected']['spell_name']:
        chance = get_casting_chance(current_wizard, 1)
        print(f"Meditate chance: {chance * 10}%")
        if (random.randint(0,100) < chance * 10) and len(wizards[current_wizard]['spell_book']) < MAX_SPELLS:
            wizards[current_wizard]['spell_book'].append(random.choice(spell_list[2:][:-1]))
            animations.append({'title': 'spell', 'rate': 200, 'x': wizards[current_wizard]['x'], 'y': wizards[current_wizard]['y'], 'frame_set': [("attack" + str(i), PALETTE[random.randint(1,15)]) for i in range(1,5)], 'destination': None})
            spell_succeeds()
        else:
            messageText = "SPELL FAILS" # Don't call spell_fails() because meditate is permanent
            wizards[current_wizard]['selected'] = None

        wizards[current_wizard]['has_moved'] = True
        # TODO: Set mount's has_moved to True if mounted 
            
        return True

    elif 'creature_cast_spell' in wizards[current_wizard]['selected']['spell_name']:

        obstructions = [d for d in wizards + creations if d.get('x') == cursor_pos[0] and d.get('y') == cursor_pos[1]]
        if obstructions: 
            print(f"Can't cast over {obstructions[0]['name']}")
            return False


        animations.append({'title': 'summon', 'rate': 20, 'x': cursor_pos[0], 'y': cursor_pos[1], 'frame_set': [("twirl" + str(i), PALETTE[random.randint(1,7)]) for i in range(10)] + [('twirl0', BRIGHT_WHITE)], 'destination': None})
        animations.append({'title': 'beam', 'rate': 5, 'x': wizards[current_wizard]['x'], 'y': wizards[current_wizard]['y'], 'dest_x': cursor_pos[0], 'dest_y': cursor_pos[1], 'colour': CYAN})

        create_creation(get_creature_name_from_spell(wizards[current_wizard]['selected']['spell_name']),
            current_wizard, cursor_pos[0], cursor_pos[1], wizards[current_wizard]['illusion'], False)
        
        spell_succeeds()
        return True

    elif wizards[current_wizard]['selected']['spell_name'] in buffs:
        # Buff spell
        if buffs[0] in wizards[current_wizard]['selected']['spell_name']:
            # Sword
            wizards[current_wizard]['frame_set'] = [('modwizard' + str(i), PALETTE[wizards[current_wizard]['palette']]) for i in range(0, 3)]
            wizards[current_wizard]['combat'] += 4
            wizards[current_wizard]['armed'] = True

        elif buffs[1] in wizards[current_wizard]['selected']['spell_name']:
            # Knife
            wizards[current_wizard]['frame_set'] = [('modwizard' + str(i), PALETTE[wizards[current_wizard]['palette']]) for i in range(3, 6)]
            wizards[current_wizard]['combat'] += 2
            wizards[current_wizard]['armed'] = True

      
        elif buffs[2] in wizards[current_wizard]['selected']['spell_name']:
            # Armour
            wizards[current_wizard]['frame_set'] = [('modwizard6', PALETTE[wizards[current_wizard]['palette']])]
            wizards[current_wizard]['defence'] = 8
        
        elif buffs[3] in wizards[current_wizard]['selected']['spell_name']:
            # Shield
            wizards[current_wizard]['frame_set'] = [('modwizard7', PALETTE[wizards[current_wizard]['palette']])]
            wizards[current_wizard]['defence'] += 2

        elif buffs[4] in wizards[current_wizard]['selected']['spell_name']:
            # Wings
            wizards[current_wizard]['flying'] = True
            wizards[current_wizard]['movement'] = 6
            wizards[current_wizard]['frame_set'] = [('modwizard' + hex(i)[2:].upper(), PALETTE[wizards[current_wizard]['palette']]) for i in range(8, 11)] 
            
        elif buffs[5] in wizards[current_wizard]['selected']['spell_name']:
            # Bow
            wizards[current_wizard]['rangedCombat'] = 3
            wizards[current_wizard]['rangedCombatRange'] = 6
            wizards[current_wizard]['frame_set'] = [('modwizard' + hex(i)[2:].upper(), PALETTE[wizards[current_wizard]['palette']]) for i in range(11, 15)]

        else:
            print('uncaught buff')
            return False

        animations.append({'title': 'spell', 'rate': 10, 'x': wizards[current_wizard]['x'], 'y': wizards[current_wizard]['y'], 'frame_set': [("attack" + str(i), PALETTE[random.randint(1,7)]) for i in range(1,5)], 'destination': None})
        spell_succeeds()
        return True
        
    elif 'chaos_law_spell' in wizards[current_wizard]['selected']['spell_name']:
        spell_succeeds()
        return True
    
    elif 'shadow_form_spell' in wizards[current_wizard]['selected']['spell_name']:
        wizards[current_wizard]['movement'] = 3
        wizards[current_wizard]['shadow'] = True
        wizards[current_wizard]['frame_set'] = [('', PALETTE[wizards[current_wizard]['palette']]), ('', BLACK)] 

        animations.append({'title': 'spell', 'rate': 10, 'x': wizards[current_wizard]['x'], 'y': wizards[current_wizard]['y'], 'frame_set': [("attack" + str(i), PALETTE[random.randint(1,7)]) for i in range(1,5)], 'destination': None})
        spell_succeeds()
        return True
    
    elif 'lightning_spell' in wizards[current_wizard]['selected']['spell_name']:
        animations.append({'title': 'beam', 'rate': 90, 'x': wizards[current_wizard]['x'], 'y': wizards[current_wizard]['y'], 'dest_x': cursor_pos[0], 'dest_y': cursor_pos[1], 'colour': BRIGHT_BLUE})
        attack_stat = 4 if 'Magic Bolt' in wizards[current_wizard]['selected']['spell_name'] else 8
        attack_stat += wizards[current_wizard]['ability']
        collisions = get_collisions(creations, cursor_pos[0], cursor_pos[1])
        if collisions:
            animations.append({'title': 'attack', 'rate': 20, 'x': cursor_pos[0], 'y': cursor_pos[1], 'frame_set': [("attack" + str(i), BRIGHT_BLUE) for i in range(1,5)], 'destination': None})
            if attack(collisions[0], attack_stat, True):
                kill(collisions[0], False)
                animations.append({'title': 'explosion', 'rate': 30, 'x': cursor_pos[0], 'y': cursor_pos[1], 'frame_set': [("explosion" + str(i), BRIGHT_WHITE) for i in range(0,7)], 'destination': None})
                spell_succeeds()
                return True
       
        spell_fails()
        return True

    elif 'subversion_spell' in wizards[current_wizard]['selected']['spell_name']:
        animations.append({'title': 'beam', 'rate': 10, 'x': wizards[current_wizard]['x'], 'y': wizards[current_wizard]['y'], 'dest_x': cursor_pos[0], 'dest_y': cursor_pos[1], 'colour': PALETTE[wizards[current_wizard]['palette']]})
        collisions = get_collisions(creations, cursor_pos[0], cursor_pos[1])
        if collisions:
            if get_rider(collisions[0]):
                print(f"Can't subvert a ridden mount")
                spell_fails()
                return True
            
            collisions[0]['owner'] = current_wizard
            print(f"{collisions[0]['name']} has defected to {wizards[current_wizard]['name']}!")
    
            animations.append({'title': 'attack', 'rate': 20, 'x': cursor_pos[0], 'y': cursor_pos[1], 'frame_set': [("attack" + str(i), PALETTE[wizards[current_wizard]['palette']]) for i in range(1,5)], 'destination': None})
            
            spell_succeeds()
            return True

        spell_fails()
        return True

    elif 'raise_dead_spell' in wizards[current_wizard]['selected']['spell_name']:
        animations.append({'title': 'beam', 'rate': 1, 'x': wizards[current_wizard]['x'], 'y': wizards[current_wizard]['y'], 'dest_x': cursor_pos[0], 'dest_y': cursor_pos[1], 'colour': MAGENTA})

        collisions = get_collisions(creations, cursor_pos[0], cursor_pos[1])
        if collisions:
            creatures.append(collsion[0])
            corpses.remove(collision[0])
            ceatures[-1]['owner'] = current_wizard
            creatures[-1]['data']['status'].append(F_UNDEAD)
            print(f"{creatures[-1]['name']} has been raised by {wizards[current_wizard]['name']}!")

            animations.append({'title': 'attack', 'rate': 2, 'x': cursor_pos[0], 'y': cursor_pos[1], 'frame_set': [("attack" + str(i), MAGENTA) for i in range(1,5)], 'destination': None})
            spell_succeeds()
            return True

        spell_fails()
        return True # Spell was succesfully attempted; not necessarily sucessfully cast

    elif 'wall_spell' in wizards[current_wizard]['selected']['spell_name']:
        castsRemaining = wizards[current_wizard]['multicast']
        messageText = f"{wizards[current_wizard]['name']}  {clean_label(wizards[current_wizard]['selected']['label'])}" + (f" {wizards[current_wizard]['selected']['distance']}" if wizards[current_wizard]['selected']['distance'] > 0 else "") + (f" ({wizards[current_wizard]['multicast']})" if wizards[current_wizard]['multicast'] > 1 else "")
        print(f"{wizards[current_wizard]['name']} casting {wizards[current_wizard]['selected']['spell_name']} ({castsRemaining})")
        if select_at(cursor_pos[0], cursor_pos[1]) :
            return False

        animations.append({'title': 'summon', 'rate': 20, 'x': cursor_pos[0], 'y': cursor_pos[1], 'frame_set': [("twirl" + str(i), PALETTE[random.randint(1,7)]) for i in range(10)] + [('twirl0', BRIGHT_WHITE)], 'destination': None})
        animations.append({'title': 'beam', 'rate': 5, 'x': wizards[current_wizard]['x'], 'y': wizards[current_wizard]['y'], 'dest_x': cursor_pos[0], 'dest_y': cursor_pos[1], 'colour': CYAN})
        create_creation('wall', current_wizard, cursor_pos[0], cursor_pos[1], False, False)

        if castsRemaining <= 1:
            spell_succeeds()
            return True
        else: 
            wizards[current_wizard]['multicast'] -= 1
            print(f"Casts remaining: {wizards[current_wizard]['multicast']}")
            return False

    elif 'trees_castles_spell' in wizards[current_wizard]['selected']['spell_name']:
        castsRemaining = wizards[current_wizard]['multicast']
        messageText = f"{wizards[current_wizard]['name']}  {clean_label(wizards[current_wizard]['selected']['label'])}" + (f" {wizards[current_wizard]['selected']['distance']}" if wizards[current_wizard]['selected']['distance'] > 0 else "") + (f" ({wizards[current_wizard]['multicast']})" if wizards[current_wizard]['multicast'] > 1 else "") # spell label or blank
        print(f"{messageText}")

        creatureName = get_creature_name_from_spell(wizards[current_wizard]['selected']['spell_name'])
        data = get_creature_stats(creatureName)

        if F_EXPIRES_SPELL in data['status']:
            # Auto cast Magic Woods: Proceed through progressively further away rings (squares with a hole) around the centre
            for radius in range(1, wizards[current_wizard]['selected']['distance']):  
                # ring = get_ring(wizards[current_wizard]['x'], wizards[current_wizard]['y'], radius, 1, 1) # Get a list of mutable lists describing a square ring n tiles away
                ring = get_spiral_ring(radius)
                for location in ring:
                    locX, locY = location[0] + wizards[current_wizard]['x'], location[1] + wizards[current_wizard]['y']

                    obstruction = get_obstruction(locX, locY)
                    
                    if not check_los(wizards[current_wizard], locX, locY):
                        continue
                    if obstruction: 
                        continue  # Something in the way
                    if adjacent_tree_check(locX, locY): 
                        continue
                    if locX < 2 or locX > ARENA_COLUMNS - 1:
                        continue # outside horizontal bounds
                    if locY < 2 or locY > ARENA_ROWS - 1:
                        continue # outside vertical bounds

                    # placement
                    animations.append({'title': 'summon', 'rate': 20, 'x': locX, 'y': locY, 'frame_set': [("twirl" + str(i), PALETTE[random.randint(1,7)]) for i in range(10)] + [('twirl0', BRIGHT_WHITE)], 'destination': None})
                    animations.append({'title': 'beam', 'rate': 20, 'x': wizards[current_wizard]['x'], 'y': wizards[current_wizard]['y'], 'dest_x': locX, 'dest_y': locY, 'colour': WHITE})
                    create_creation(creatureName, current_wizard, locX, locY, False, False)
                    castsRemaining -= 1 

                    if castsRemaining <= 0: break
                if castsRemaining <= 0: break
            
            spell_succeeds(8)
            return True
        
        else: # Not a Magic Wood, manual casting is allowed
            if select_at(cursor_pos[0], cursor_pos[1]) :
                # Can't place a tree or castle over a live obstruction
                return False

            if 'shadow' in wizards[current_wizard]['selected']['spell_name'].lower():
                if adjacent_tree_check(cursor_pos[0], cursor_pos[1]):
                    print("Can't place a tree next to any other tree.")
                    return False
            animations.append({'title': 'summon', 'rate': 20, 'x': cursor_pos[0], 'y': cursor_pos[1], 'frame_set': [("twirl" + str(i), PALETTE[random.randint(1,7)]) for i in range(10)] + [('twirl0', BRIGHT_WHITE)], 'destination': None})
            animations.append({'title': 'beam', 'rate': 5, 'x': wizards[current_wizard]['x'], 'y': wizards[current_wizard]['y'], 'dest_x': cursor_pos[0], 'dest_y': cursor_pos[1], 'colour': CYAN})
            create_creation(creatureName, current_wizard, cursor_pos[0], cursor_pos[1], False, False)
            castsRemaining -= 1 

            if castsRemaining < 1:
                spell_succeeds()
                return True

            wizards[current_wizard]['multicast'] -= 1
            print(f"Casts remaining: {wizards[current_wizard]['multicast']}")
            # return False  

    elif 'dark_power_spell':
        castsRemaining = wizards[current_wizard]['multicast']
        messageText = f"{wizards[current_wizard]['name']}  {clean_label(wizards[current_wizard]['selected']['label'])}" + (f" {wizards[current_wizard]['selected']['distance']}" if wizards[current_wizard]['selected']['distance'] > 0 else "") + (f" ({wizards[current_wizard]['multicast']})" if wizards[current_wizard]['multicast'] > 1 else "")
        print(f"{wizards[current_wizard]['name']} casting {wizards[current_wizard]['selected']['spell_name']} ({castsRemaining})")
        target = select_at(cursor_pos[0], cursor_pos[1])
        if not target: return False # This spell needs a target
        if string_in_object(target, F_INVULN): return False # This spell can't target walls, castles, fire etc.
        attack_stat = 3 * abs(wizards[current_wizard]['selected']['law'])
        attack_stat += wizards[current_wizard]['ability'] 

        animations.append({'title': 'attack', 'rate': 20, 'x': cursor_pos[0], 'y': cursor_pos[1], 'frame_set': [("attack" + str(i), BRIGHT_BLUE) for i in range(1,5)], 'destination': None})
        if attack(target, attack_stat, True):
            if not is_wizard(target):
                kill_creation(target, False)
                animations.append({'title': 'explosion', 'rate': 30, 'x': cursor_pos[0], 'y': cursor_pos[1], 'frame_set': [("explosion" + str(i), BRIGHT_WHITE) for i in range(0,7)], 'destination': None})
                spell_succeeds()
                return True
            else:
                kill_wizards_creations(target['owner'])
                spell_succeeds()
                return True
        else:
            castsRemaining -=1

        if castsRemaining < 1:
            spell_succeeds()
            return True
        else: 
            wizards[current_wizard]['multicast'] -= 1
            print(f"Casts remaining: {wizards[current_wizard]['multicast']}")
            return False

    return False

def is_wizard(object):
    return True if 'spell_book' in object else False 

def is_flyer(object):
    return object.get('flying') or string_in_object(object, F_FLYING)

def ranged_attack(target, x0: int, y0: int, attack_stat: int, magical: bool = False):
    global creations, wizards, messageText
    animations.append({'title': 'attack', 'rate': 20, 'x': cursor_pos[0], 'y': cursor_pos[1], 'frame_set': [("attack" + str(i), WHITE) for i in range(1,5)], 'destination': None})
    animations.append({'title': 'beam', 'rate': 60, 'x': x0, 'y': y0, 'dest_x': cursor_pos[0], 'dest_y': cursor_pos[1], 'colour': WHITE})
    messageText = ''
    if target: 
        if(attack(target, attack_stat, magical)):
            if kill(target): print(f"{target['name']} destroyed")
            else: print('Not vulnerable to this attack.')
    return

def move(activeObject, source_x, source_y, dest_x, dest_y):
    global creations, wizards, rangedCombatTime, messageText, moves_remaining, selection, cursor_type, sounds

    attack_stat, activeIsMount, obstructionRider, mounting = None, False, None, False
    obstruction = get_obstruction(dest_x, dest_y, activeObject)
    activeObject['engaged'] = check_engagement(activeObject)
    if obstruction:
        print(f"OBSTRUCTION: {obstruction['name']}")
        if string_in_object(obstruction, F_INVULN) and not string_in_object(obstruction, F_STRUCT): return False # Can't attack invulnerables; may be structure

        elif is_wizard(activeObject) and ( string_in_object(obstruction, F_MOUNT) or string_in_object(obstruction, F_MOUNT_ANY) ):
            # Mount logic
            obstructionRider = get_rider(obstruction)
            if (activeObject['owner'] == obstruction['owner']) or (F_MOUNT_ANY in obstruction['data']['status'] and obstructionRider == None):
                # Friendly mount or empty mount_any
                activeObject['mounted'] = True # Flag it and continue to the move without attacking
                moves_remaining = 0
                mounting = True

        elif activeObject['owner'] == obstruction['owner'] and not string_in_object(obstruction, F_ENGULFS):
            # Can not attack allies unless engulfers
            return False   

        elif string_in_object(obstruction, F_UNDEAD) and not (activeObject.get('armed') or string_in_object(activeObject, F_UNDEAD)):
            messageText = 'UNDEAD-CANNOT BE ATTACKED'
            sounds.append(SND_UNDEAD)
            return False    # Not equipped to attack Undead
        
        else:
            # No reason to interfere with move apart from violently removing the obstruction:
            pass
            
        if not mounting:
            # ATTACK BEGINS HERE
            print(f"{activeObject['name']} is attacking {obstruction['name']}")
            attack_stat = activeObject['combat'] if is_wizard(activeObject) else activeObject['data']['com']
            activeObject['has_moved'] = True

            if is_wizard(activeObject): activeObject['shadow'] = False # Wizards always lose Shadow Form when attacking
            if not melee_attack(obstruction, attack_stat): # Melee Attack Failed
                print(f"Melee attack failed.")
                attackRange = activeObject['rangedCombatRange'] if is_wizard(activeObject) else activeObject['data']['rng']
                if attackRange > 0: # We can still perform a ranged attack
                    rangedCombatTime = True
                    messageText = f"RANGED COMBAT,RANGE={attackRange}"
                    activeObject['engaged'] = True
                    return True
                else: # Attack options are exhausted. The obstruction remains. Active object stays in place and its turn is over.
                    selection = None
                    messageText = ''
                    activeObject['engaged'] = True
                    return True
            else: # Successful attack but there may still be an obstacle
                activeObject['engaged'] = False
                
                newObstruction = get_obstruction(dest_x, dest_y, activeObject)
                if newObstruction: # Unhorsed rider or liberated victim
                    print(f"SURVIVING OBSTRUCTION: {newObstruction['name']}")

                    # If an attacking wizard is not moving, they should get back on their mount rather than share the cell
                    if is_wizard(activeObject):
                        mount = get_obstruction(activeObject['x'], activeObject['y'], activeObject)
                        if mount:
                            activeObject['mounted'] = True
                            mount['has_moved'] = True
                
                    selection = None
                    messageText = ''
                    return True                    

                moves_remaining = 0
    
    else:
        # No obstruction in the space we want to move into
        if activeObject['engaged']: # Can only move into vacant cells if not engaged
            print(f"{activeObject['name']} can not move to empty cell because it is engaged")
            messageText = "ENGAGED TO ENEMY"
            sounds.append(SND_ENGAGED)
            return False

    # Now we continue to move into the destination cell, ending move as appropriate
    if not is_wizard(activeObject): # We only check non-wizards for being mounts
        if F_MOUNT in activeObject['data']['status']: # This is a mount
            if wizards[activeObject['owner']]['mounted'] and wizards[activeObject['owner']]['x'] == source_x and wizards[activeObject['owner']]['y'] == source_y: # Its owner is mounted on this mount
                wizards[activeObject['owner']]['x'], wizards[activeObject['owner']]['y'] = dest_x, dest_y # Wizard follows mount
        elif F_TREE in activeObject['data']['status']:
            # Shadow trees don't move
            selection = None
            messageText = ''
            return True

    sounds.append(SND_WALK)
    activeObject['x'], activeObject['y'] = dest_x, dest_y
    if is_flyer(activeObject):
        moves_remaining = 0
        activeObject['has_moved'] = True
    else: moves_remaining -= 1
    if math.ceil( math.sqrt((dest_x - source_x) ** 2 + (dest_y - source_y) ** 2) ) > 1: moves_remaining -= 0.5
    cursor_pos[0], cursor_pos[1] = dest_x, dest_y
    messageText = f"MOVEMENT POINTS LEFT={math.ceil(moves_remaining)}"

    if moves_remaining <= 0:

        cursor_type = CURSOR_FRAME
        range = activeObject['rangedCombatRange'] if is_wizard(activeObject) else activeObject['data']['rng']
        if range > 0: 
            messageText = f"RANGED COMBAT,RANGE={range}"
            rangedCombatTime = True
        else:
            rangedCombatTime = False
            selection = None
            messageText = ''
        activeObject['has_moved'] = True
        

    return True

def dismount(thisWizard: int, x: int, y: int):
    global wizards
    wizards[thisWizard]['mounted'] = False
    wizards[thisWizard]['x'], wizards[thisWizard]['y'] = x,y

def get_rider(mountObject):
    # if not string_in_object(mountObject, F_MOUNT): return None
    for wizard in wizards:
        if wizard['mounted'] and wizard['x'] == mountObject['x'] and wizard['y'] == mountObject ['y']:
            print(f"{mountObject['name']} ridden by {wizard['name']}")
            return wizard
    print(f"{mountObject['name']} has no rider")
    return None

def readable_alignment(alignment: int) -> str:
    if alignment > 0: return f"Law {abs(alignment)}"
    elif alignment < 0: return f"Chaos {abs(alignment)}"
    else: return "Neutral" 

def get_creature_stats(creatureName: str):
    for creature in creature_list:
        if creature['name'] == creatureName: return creature

def get_creature_name_from_spell(spell_name: str) -> str:
    s = spell_name.find("(")
    e = spell_name.find(")")
    return spell_name[s + 1:e].lower().replace(' ','_') if s != -1 and e != -1 else None

def clean_status(status: list) -> str:

    def space_before_caps(s: str) -> str:
        return ''.join(' ' + c if i and c.isupper() else c for i, c in enumerate(s))

    return space_before_caps(",".join(status)).replace('trans','eth').upper()

def describe_cell():
    global messageText
    messageText = ''
    objects = get_collisions(creations + wizards + corpses, cursor_pos[0], cursor_pos[1])
    if objects:
        extras = ' `7#`6' if len(objects)>1 else ''
        description = objects[0]['name'] if(is_wizard(objects[0])) else clean_label(objects[0]['data']['label']) + extras + f" ({wizards[objects[0]['owner']]['name']})" # creation label or wizard name
        messageText = f"{description}"
    else:
        if current_screen == GS_ARENA: 
            if rangedCombatTime:
                range = wizards[current_wizard]['rangedCombatRange'] if is_wizard(selection) else selection['data']['rng']
                messageText = f"RANGED COMBAT,RANGE={range}"
            else:
                messageText = f"{wizards[current_wizard]['name']}'s turn"
        elif current_screen == GS_CAST:
            messageText = f"{wizards[current_wizard]['name']}  {clean_label(wizards[current_wizard]['selected']['label']) if wizards[current_wizard]['selected'] else ''}" + ( (f" {wizards[current_wizard]['selected']['distance']}" if wizards[current_wizard]['selected']['distance'] > 0 else "")  if wizards[current_wizard]['selected'] else '') + ( (f" ({wizards[current_wizard]['multicast']})" if wizards[current_wizard]['multicast'] > 1 else "")  if wizards[current_wizard]['selected'] else '' )
        else:
            # Must be inspection
            messageText = ""
    return

def handle_input(event):
    global sounds, cursor_pos, cursor_type, current_screen, messageText, num_wizards, current_wizard, wizards, selection, showBases, moves_remaining, illusion_checking, dismount_checking, rangedCombatTime, highlightWizard
    midFlight = False

    if current_screen == GS_INTRO:
        # Code to execute when current_screen is GS_INTRO
        if event.type == pygame.KEYDOWN:
            if event.key == pygame.K_ESCAPE:
                pygame.quit()
                exit(0)
            elif event.key == pygame.K_a:
                current_screen = GS_ARENA
            else:
                current_screen = GS_SETUP
    elif current_screen == GS_SETUP:
        # Code to execute when current_screen is GS_SETUP

        # Setting number of players
        if current_wizard < 1 and event.type == pygame.KEYDOWN:
            sounds.append(SND_KEY)
            if pygame.K_2 <= event.key <= pygame.K_8:
                num_wizards = event.key - pygame.K_0
            if event.key == pygame.K_x and num_wizards > MIN_WIZARDS:
                num_wizards -= 1
            elif event.key == pygame.K_w and num_wizards < MAX_WIZARDS:
                num_wizards += 1
            elif event.key == pygame.K_RETURN:
                current_wizard = 1
                return

        # Moving on to wizard config
        if current_wizard > 0 and event.type == pygame.KEYDOWN :
            sounds.append(SND_KEY)
            if event.key == pygame.K_x and wizards[current_wizard]['level'] >= 1:
                wizards[current_wizard]['level'] -= 1
            elif event.key == pygame.K_w and wizards[current_wizard]['level'] < 8:
                wizards[current_wizard]['level'] += 1
            elif event.key == pygame.K_a:
                if (wizards[current_wizard]['sprite'] > 1):
                    wizards[current_wizard]['sprite'] -= 1
                else: wizards[current_wizard]['sprite'] = 8
            elif event.key == pygame.K_d:
                if (wizards[current_wizard]['palette'] == 14):
                    wizards[current_wizard]['palette'] = 1                
                elif wizards[current_wizard]['palette'] >= 7:
                    wizards[current_wizard]['palette'] = 14
                else:
                    wizards[current_wizard]['palette'] += 1
            elif event.key == pygame.K_s:
                current_screen = GS_NAME
            elif event.key == pygame.K_RETURN:
                if current_wizard >= num_wizards:
                    # SETUP complete - game initialisation starts here
                    current_wizard = 1
                    prepare_wizards()
                    prepare_starting_positions()
                    current_screen = GS_MENU
                else:
                    current_wizard += 1
            elif event.key == pygame.K_BACKSPACE: 
                if current_wizard >0: current_wizard -= 1
            return
        elif event.type == pygame.KEYDOWN and event.key == pygame.K_BACKSPACE: current_screen = GS_INTRO         
    elif current_screen == GS_NAME:
        # Code to execute when current_screen is GS_NAME
        if event.type == pygame.KEYDOWN:
            if (event.key == pygame.K_ESCAPE or event.key == pygame.K_RETURN) and len(wizards[current_wizard]['name'])>0:
                current_screen = GS_SETUP
            elif (pygame.K_a <= event.key <= pygame.K_z) and len(wizards[current_wizard]['name'])<20:
                sounds.append(SND_KEY)
                mods = pygame.key.get_mods()
                if mods & pygame.KMOD_SHIFT: letter = pygame.key.name(event.key).upper()
                else: letter = pygame.key.name(event.key)
                wizards[current_wizard]['name'] = wizards[current_wizard]['name'] + letter
            elif event.key == pygame.K_BACKSPACE:
                sounds.append(SND_KEY)
                wizards[current_wizard]['name'] = wizards[current_wizard]['name'][:-1]
        return
    elif current_screen == GS_MENU:
        if event.type == pygame.KEYDOWN:
            if event.key == pygame.K_1 and wizards[current_wizard]['selected']:
                sounds.append(SND_TICK)
                current_screen = GS_INFO # Examine selected spell
            elif event.key == pygame.K_2:
                sounds.append(SND_TICK)
                current_screen = GS_SELECT # Select spell from list
            elif event.key == pygame.K_3:
                sounds.append(SND_TICK)
                cursor_pos[0], cursor_pos[1] = wizards[current_wizard]['x'], wizards[current_wizard]['y']
                messageText = f"{wizards[current_wizard]['name']} INSPECTING ARENA"
                current_screen = GS_INSPECT # Examine arena state
            elif event.key == pygame.K_4 or event.key == pygame.K_RETURN:
                sounds.append(SND_TICK)
                if current_wizard == num_wizards: current_screen = GS_CAST
                nextWizard()

            elif event.key == pygame.K_ESCAPE or event.key == pygame.K_BACKSPACE: 
                sounds.append(SND_KEY)
                wizards[current_wizard]['selected'] = None
        return
    elif current_screen == GS_SELECT:
        # Code to execute when current_screen is GS_SELECT
        if event.type == pygame.KEYDOWN:
            # print(f'key: {event.key} checking? {illusion_checking}')
            if illusion_checking:
                if event.key == pygame.K_y:
                    wizards[current_wizard]['illusion'] = True
                    illusion_checking = False
                    messageText = ""
                    current_screen = GS_MENU
                elif event.key == pygame.K_n:
                    wizards[current_wizard]['illusion'] = False
                    illusion_checking = False
                    messageText = ""
                    current_screen = GS_MENU
            else:
                if (event.key == pygame.K_ESCAPE or event.key == pygame.K_BACKSPACE):
                    current_screen = GS_MENU
                elif (pygame.K_a <= event.key <= pygame.K_a + len(wizards[current_wizard]['spell_book']) - 1):
                    wizards[current_wizard]['selected'] = wizards[current_wizard]['spell_book'][event.key-pygame.K_a]
                    spell_name = wizards[current_wizard]['selected']['spell_name']
                    wizards[current_wizard]['multicast'] = wizards[current_wizard]['selected']['multicast']
                    print(f"{ wizards[current_wizard]['name']} will cast { wizards[current_wizard]['selected']['spell_name']} { wizards[current_wizard]['multicast']} times")
                    if ( 'creature_cast_spell' in spell_name ) and ( '(Magic Fire)' not in spell_name ) and ( '(Goey Blob)' not in spell_name ) :
                        messageText = " ILLUSION? (PRESS Y OR N)  "
                        illusion_checking = True
                    else: 
                        sounds.append(SND_TICK)
                        current_screen = GS_MENU

        return

    elif current_screen == GS_CAST or current_screen == GS_ARENA or current_screen == GS_INSPECT:
        # Code to execute when current_screen is GS_ARENA
        if event.type == pygame.KEYDOWN:
            
            if dismount_checking:
                if event.key == pygame.K_y: 
                    dismount_checking = False
                    print(f"{wizards[current_wizard]['name']} is attempting to dismount.")
                    selection = wizards[current_wizard]
                    sounds.append(SND_SELECTED)
                    moves_remaining = selection['movement']
                    selection['mounted'] = False
                    messageText = f"MOVEMENT POINTS LEFT={moves_remaining}"
                elif event.key == pygame.K_n: 
                    messageText = f"MOVEMENT POINTS LEFT={moves_remaining}"
                    dismount_checking = False
                    return
                return

            # Pre-flight checks
            if selection: midFlight = is_flyer(selection)
            if midFlight: cursor_type = CURSOR_FLY

            if event.key == pygame.K_i and current_screen == GS_INSPECT: current_screen = GS_INFO_ARENA
            elif event.key == pygame.K_TAB and (current_screen == GS_ARENA or current_screen == GS_INSPECT): showBases = not showBases

            elif (pygame.K_1 <= event.key <= pygame.K_9) and (current_screen == GS_ARENA or current_screen == GS_INSPECT): 
                highlightWizard = 0 if highlightWizard > 0 and (highlightWizard <= num_wizards) else event.key - pygame.K_0; return

            elif event.key == pygame.K_q:
                newX = max(cursor_pos[0] - 1,1)
                newY = max(cursor_pos[1] - 1,1)
                if current_screen == GS_ARENA and selection and not rangedCombatTime and not midFlight: move(selection, cursor_pos[0], cursor_pos[1], newX, newY)
                else: 
                    cursor_pos[0], cursor_pos[1] = newX, newY
                    describe_cell()
            elif event.key == pygame.K_w:
                newX = cursor_pos[0]
                newY = max(cursor_pos[1] - 1,1)
                if current_screen == GS_ARENA and selection and not rangedCombatTime and not midFlight: move(selection, cursor_pos[0], cursor_pos[1], newX, newY)
                else: 
                    cursor_pos[0], cursor_pos[1] = newX, newY
                    describe_cell()
            elif event.key == pygame.K_e:
                newX = min(cursor_pos[0] + 1, (ARENA_WIDTH // TILE_SIZE))
                newY = max(cursor_pos[1] - 1,1)
                if current_screen == GS_ARENA and selection and not rangedCombatTime and not midFlight: move(selection, cursor_pos[0], cursor_pos[1], newX, newY)
                else: 
                    cursor_pos[0], cursor_pos[1] = newX, newY
                    describe_cell()
            elif event.key == pygame.K_a:
                newX = max(cursor_pos[0] - 1,1)
                newY = cursor_pos[1]
                if current_screen == GS_ARENA and selection and not rangedCombatTime and not midFlight: move(selection, cursor_pos[0], cursor_pos[1], newX, newY)
                else: 
                    cursor_pos[0], cursor_pos[1] = newX, newY
                    describe_cell()
            elif event.key == pygame.K_d:
                newX = min(cursor_pos[0] + 1, (ARENA_WIDTH // TILE_SIZE))
                newY = cursor_pos[1]
                if current_screen == GS_ARENA and selection and not rangedCombatTime and not midFlight: move(selection, cursor_pos[0], cursor_pos[1], newX, newY)
                else: 
                    cursor_pos[0], cursor_pos[1] = newX, newY
                    describe_cell()
            elif event.key == pygame.K_z:
                newX = max(cursor_pos[0] - 1,1)
                newY = min(cursor_pos[1] + 1, (ARENA_HEIGHT // TILE_SIZE))
                if current_screen == GS_ARENA and selection and not rangedCombatTime and not midFlight: move(selection, cursor_pos[0], cursor_pos[1], newX, newY)
                else: 
                    cursor_pos[0], cursor_pos[1] = newX, newY
                    describe_cell()
            elif event.key == pygame.K_x:
                newX = cursor_pos[0]
                newY = min(cursor_pos[1] + 1, (ARENA_HEIGHT // TILE_SIZE))
                if current_screen == GS_ARENA and selection and not rangedCombatTime and not midFlight: move(selection, cursor_pos[0], cursor_pos[1], newX, newY)
                else: 
                    cursor_pos[0], cursor_pos[1] = newX, newY
                    describe_cell()
            elif event.key == pygame.K_c:
                newX = min(cursor_pos[0] + 1, (ARENA_WIDTH // TILE_SIZE))
                newY = min(cursor_pos[1] + 1, (ARENA_HEIGHT // TILE_SIZE))
                if current_screen == GS_ARENA and selection and not rangedCombatTime and not midFlight: move(selection, cursor_pos[0], cursor_pos[1], newX, newY)
                else: 
                    cursor_pos[0], cursor_pos[1] = newX, newY
                    describe_cell()
            elif event.key == pygame.K_k:
                # K for cancel selection, naturally
                if current_screen == GS_CAST:
                    # Cancelling spell cast
                    wizards[current_wizard]['selected'] = None
                    if current_wizard == num_wizards: 
                        spread_spreaders()
                        current_screen = GS_ARENA
                    nextWizard()      
                    return
                else:
                    if rangedCombatTime:
                        # Cancelling ranged attack
                        rangedCombatTime = False
                    else:
                        # Cancelling a move part way through
                        moves_remaining = 0
                        if selection:
                            for objects in wizards + creations:
                                if objects['name'] == selection['name'] and objects['x'] == cursor_pos[0] and objects['y'] == cursor_pos[1]:
                                    objects['has_moved'] = True
                                    
                    selection = None
                    messageText = ''
                    return
            elif event.key == pygame.K_s:
                if current_screen == GS_CAST:
                    if wizards[current_wizard]['selected']:
                        # Casting a spell
                        if cast_attempt(): 
                            if current_wizard == num_wizards: 
                                spread_spreaders()
                                current_screen = GS_ARENA
                            nextWizard()
                            return
                elif current_screen == GS_ARENA:
                    if selection:
                        # There's already a selection: this must be a flight or ranged combat
                        if rangedCombatTime:
                            # It's ranged combat
                            range = selection['data']['rng'] if 'data' in selection else selection['rangedCombatRange']

                            if get_distance( [ selection['x'], selection['y'] ] , [ cursor_pos[0], cursor_pos[1] ] ) > range:
                                messageText = 'OUT OF RANGE'
                                return
                            if not check_los(selection, cursor_pos[0], cursor_pos[1]):
                                messageText = 'NO LINE OF SIGHT'
                                return

                            target = select_at(cursor_pos[0], cursor_pos[1])
                            attack_stat = selection['data']['rcm'] if 'data' in selection else selection['rangedCombat']
                            if target: print(f"{target['name']} is under attack by {selection['name']} ({attack_stat})")
                            if is_wizard(selection): selection['shadow'] = False # Wizards always lose Shadow Form when attacking
                            ranged_attack(target, selection['x'], selection['y'], attack_stat)
                            selection = None
                            rangedCombatTime = False
                        else: # Not ranged combat; must be a flyer
                            selection['engaged'] = check_engagement(selection)
                            if selection['engaged']: return
                            newX, newY = cursor_pos[0], cursor_pos[1]
                            move(selection, selection['x'], selection['y'], newX, newY)
                            cursor_type = CURSOR_FRAME

                    else:
                        # New selection
                        selection = select_at(cursor_pos[0], cursor_pos[1])
                        if selection:
                            print(f"You selected {selection['name']}")
                            if (selection['has_moved'] or selection['owner'] != current_wizard):
                                print('Moved or not owned')
                                selection = None
                                return
                            elif not is_wizard(selection):
                                # print(selection)
                                # It's a creation, but it may be immobile
                                moves_remaining = selection['data']['mov']
                                if moves_remaining == 0:
                                    print('Not moveable')
                                    # If there's a rider, given that this selection is static, the rider is selected automatically instead
                                    rider = get_rider(selection)
                                    if rider:
                                        selection = rider
                                        moves_remaining = selection['movement'] if selection else 0
                                        if selection: selection['mounted'] = False 

                                    elif F_TREE in selection['data']['status'] and F_MOUNT_ANY not in selection['data']['status']:
                                        # Shadow trees just have to be different, don't they?
                                        moves_remaining = 0
                                        print("Shadow tree selected.")
                                    else:
                                        selection = None
                                        
                                    if selection: selection['engaged'] = check_engagement(selection) 
                                    return
                                else:
                                    print(f"{selection['name']} has {moves_remaining} moves remaining.")
                                    # If F_MOUNT, check for a mounted wizard at its location and ask if they want to dismount before moving                            
                                    if string_in_object(selection, F_MOUNT): 
                                        if get_rider(selection): dismount_checking = True
                                        return

                            else:
                                # Wizard
                                # print(selection)
                                moves_remaining = selection['movement']
                                cursor_type = CURSOR_FLY if selection['flying'] else CURSOR_FRAME 

                            if not is_wizard(selection): cursor_type = CURSOR_FLY if F_FLYING in selection['data']['status'] else CURSOR_FRAME

                            print(f"Selection: {selection['name']} with {moves_remaining} moves")
                            messageText = f"MOVEMENT POINTS LEFT={moves_remaining}"
                            if selection: 
                                sounds.append(SND_SELECTED)
                                selection['engaged'] = check_engagement(selection) 

                        return

                elif current_screen == GS_INSPECT:
                    current_screen = GS_INFO_ARENA
            elif event.key == pygame.K_0 and current_screen == GS_ARENA and selection == None: # Must (K)cancel before ending
                # End round or turn
                if current_wizard == num_wizards: 
                    # Set wizards and creations to unmoved
                    for obj_list in [wizards, creations]: [obj.update({'has_moved': False}) for obj in obj_list]
                    current_screen = GS_MENU
                nextWizard()
            elif current_screen == GS_INSPECT: 
                current_screen = GS_MENU
            else: print(f"Uncaught keypress: {event.key}")

    elif current_screen == GS_INFO or current_screen == GS_INFO_ARENA:
        if event.type == pygame.KEYDOWN:
            current_screen = GS_MENU

    elif current_screen == GS_GAME_OVER and event.type == pygame.KEYDOWN:
        print("Bye!")
        exit()
    else:
        print(f"Unhandled event: {event}")

def render_intro():
    pygame.draw.rect(screen, RED, (0, 0, SCREEN_WIDTH, SCREEN_HEIGHT))
    pygame.draw.rect(screen, BLACK, (BORDER_WIDTH // 2 , BORDER_WIDTH // 2, ARENA_WIDTH + BORDER_WIDTH, ARENA_HEIGHT + BORDER_WIDTH))
    sprint(screen, 0, 1, 'CHAOS - THE BATTLE OF WIZARDS', MAGENTA, True)
    sprint(screen, 0, 2, 'By Julian Gollop', RED, True)
    sprint(screen, 0, 4, 'ENTRO.PY', BRIGHT_BLUE, True)
    sprint(screen, 0, 5, '40 years of Chaos', BLUE, True)

    sprint(screen, 0, 7, 'Python tribute by', CYAN, True)
    sprint(screen, 0, 8, 'Kerry Fraser-Robinson', CYAN, True)
    sprint(screen, 0, 10, 'Press any key to start', YELLOW, True)
    border(screen, MAGENTA)

def render_setup():
    global current_wizard, wizards
    pygame.draw.rect(screen, BLUE, (0, 0, SCREEN_WIDTH, SCREEN_HEIGHT))
    pygame.draw.rect(screen, BLACK, (BORDER_WIDTH // 2 , BORDER_WIDTH // 2, ARENA_WIDTH + BORDER_WIDTH, ARENA_HEIGHT + BORDER_WIDTH))
    border(screen, CYAN)
    sprint(screen, 6, 1, f"How many wizards? ({MIN_WIZARDS}-{MAX_WIZARDS}) {num_wizards}", WHITE)

    for c in range(current_wizard):
        sprint(screen, 10, c + 2, f"{wizards[c + 1]['name']}", WHITE)
        sprite_at(screen, 3, c + 2, f"character_{wizards[c + 1]['sprite']}_sprite", PALETTE[wizards[c + 1]['palette']])
        if (wizards[c + 1]['level'] == 0): 
            sprint(screen, (ARENA_COLUMNS * 2) - 6, c + 2, 'Human', WHITE)
        else:
            sprint(screen, (ARENA_COLUMNS * 2) - 6, c + 2, f"Lvl {wizards[c + 1]['level']}", WHITE)

    if (current_wizard>0): sprint(screen, 6, ARENA_ROWS, "A/D S <BKSP><ENTER> W/X", YELLOW)
    else: 
        sprint(screen, 18, 3, "W/X to change", YELLOW)
        sprint(screen, 12, 4, "<ENTER> to continue", YELLOW)
        sprint(screen, 14, 5, "<BKSP> to go back", YELLOW)

def render_name():
    global current_wizard, wizards
    pygame.draw.rect(screen, RED, (0, 0, SCREEN_WIDTH, SCREEN_HEIGHT))
    pygame.draw.rect(screen, BLACK, (BORDER_WIDTH // 2 , BORDER_WIDTH // 2, ARENA_WIDTH + BORDER_WIDTH, ARENA_HEIGHT + BORDER_WIDTH))
    sprite_at(screen, 2, 4, f"character_{wizards[current_wizard]['sprite']}_sprite", PALETTE[wizards[current_wizard]['palette']])
    sprint(screen, 8, 4, f"{wizards[current_wizard]['name']}", WHITE)
    sprint(screen, 0, 7, "A-Z  <BSKP>  <ESC>/<ENTER>", YELLOW, True)

def render_menu():
    pygame.draw.rect(screen, RED, (0, 0, SCREEN_WIDTH, SCREEN_HEIGHT))
    pygame.draw.rect(screen, BLACK, (BORDER_WIDTH // 2 , BORDER_WIDTH // 2, ARENA_WIDTH + BORDER_WIDTH, ARENA_HEIGHT + BORDER_WIDTH))
    border(screen, YELLOW)
    sprint(screen, 7, 1, wizards[current_wizard]['name'], YELLOW)
    sprint(screen, 7, 2, get_world_alignment_string(), YELLOW)
    sprint(screen, 9, 3, '1.EXAMINE SPELL', CYAN)
    sprint(screen, 9, 5, '2.SELECT SPELL', CYAN)
    sprint(screen, 9, 7, '3.EXAMINE BOARD', CYAN)
    sprint(screen, 9, 9, '4.CONTINUE', CYAN)
    if wizards[current_wizard]['selected']:
        sprint(screen, 11, 5, f"CHANGE `{(6 if wizards[current_wizard]['illusion'] else 5)}{clean_label(wizards[current_wizard]['selected']['label']).ljust(13)}", CYAN)

    turnString = f"Turn {turn}.{current_wizard}"
    sprint(screen, 1 + (ARENA_COLUMNS * 2) - len(turnString),ARENA_ROWS, turnString, YELLOW, False)

def render_select():

    sprint(screen, 1, 0, f"{wizards[current_wizard]['name']}'s SPELLS", YELLOW)
    for i in range(0, len(wizards[current_wizard]['spell_book']), 2):
        sprint(screen, 1, i // 2 + 1, f"{chr(ord('A')+i)}{get_alignment_character(wizards[current_wizard]['spell_book'][i]['law'])}{clean_label(wizards[current_wizard]['spell_book'][i]['label'])}", get_chance_color(get_casting_chance(current_wizard, i)))
        # Check if there is a next item to avoid IndexError
        if i + 1 < len(wizards[current_wizard]['spell_book']):
            sprint(screen, 18, i // 2 + 1, f"{chr(ord('A')+i+1)}{get_alignment_character(wizards[current_wizard]['spell_book'][i+1]['law'])}{clean_label(wizards[current_wizard]['spell_book'][i+1]['label'])}", get_chance_color(get_casting_chance(current_wizard, i + 1)))
    
    if messageText: sprint(screen, 0, ARENA_ROWS + 1, messageText, BRIGHT_YELLOW)
    
    return

def render_info():
    global current_wizard, wizards
    def sprintMessage(text_col: int, row: int, message: str, lineWidth: int = ARENA_ROWS * 2 - 2):
        start = 0

        while start < len(message):
            end = min(start + lineWidth, len(message))
            if end < len(message):  # Check if we are not at the end of the message
                # Extend the line to the next space/comma/period if it's close
                while end < len(message) and message[end] not in ' ,.':
                    end += 1
                if end < len(message):
                    end += 1  # Include the space/comma/period in the line

            line = message[start:end]
            sprint(screen, text_col, row, line, YELLOW)
            row += 1
            start = end

    pygame.draw.rect(screen, BLUE, (0, 0, SCREEN_WIDTH, SCREEN_HEIGHT))
    pygame.draw.rect(screen, BLACK, (BORDER_WIDTH // 2 , BORDER_WIDTH // 2, ARENA_WIDTH + BORDER_WIDTH, ARENA_HEIGHT + BORDER_WIDTH))
    border(screen, CYAN)    

    if ('creature_cast_spell' in wizards[current_wizard]['selected']['spell_name']):
        label = clean_label(wizards[current_wizard]['selected']['label'])
        creature_name = get_creature_name_from_spell(wizards[current_wizard]['selected']['spell_name'])
        stats = get_creature_stats(creature_name)
        sprint(screen, 3, 1, label, YELLOW)
        if (wizards[current_wizard]['selected']['law'] != 0): 
            sprint(screen, len(label) + 4, 1, f"({readable_alignment(wizards[current_wizard]['selected']['law'])})", CYAN)
        sprint(screen, 3, 2, clean_status(stats['status']), GREEN)

        # Static template:
        sprint(screen, 3, 3, 'COMBAT=', CYAN)
        sprint(screen, 14, 3, 'DEFENCE=', CYAN)
        sprint(screen, 3, 4, 'RANGED COMBAT=', CYAN)
        sprint(screen, 3, 5, 'RANGE=', CYAN)
        sprint(screen, 3, 6, 'MOVEMENT ALLOWANCE=', CYAN)
        sprint(screen, 3, 7, 'MANOEUVRE RATING=', CYAN) # Lower better so change to "melee presence"
        sprint(screen, 3, 8, 'MAGIC RESISTANCE=', CYAN)
        sprint(screen, 3, 9, 'CASTING CHANCE=', CYAN)
        # Values:
        sprint(screen, 10, 3, f"{stats['com']}", YELLOW)
        sprint(screen, 22, 3, f"{stats['def']}", YELLOW)
        sprint(screen, 17, 4, f"{stats['rcm']}", YELLOW)
        sprint(screen, 9, 5, f"{stats['rng']}", YELLOW)
        sprint(screen, 22, 6, f"{stats['mov']}", YELLOW)
        sprint(screen, 20, 7, f"{stats['mnv']}", YELLOW)
        sprint(screen, 20, 8, f"{stats['res']}", YELLOW)
        sprint(screen, 18, 9, f"{wizards[current_wizard]['selected']['chance'] * 10}%", YELLOW)

    else:
        # Not a creature spell
        sprint(screen, 5, 2, clean_label(wizards[current_wizard]['selected']['label']), YELLOW)
        if (wizards[current_wizard]['selected']['law'] != 0): 
            sprint(screen, 5, 3, f"({readable_alignment(wizards[current_wizard]['selected']['law'])})", CYAN)
        sprint(screen, 5, 4, "CASTING CHANCE=", GREEN)
        sprint(screen, 20, 4, f"{wizards[current_wizard]['selected']['chance'] * 10}%", YELLOW)
        sprint(screen, 5, 5, "RANGE=", GREEN)
        sprint(screen, 11, 5, f"{min(20,wizards[current_wizard]['selected']['distance'])}", YELLOW)
        # sprint(screen, 5, 8, f"{wizards[current_wizard]['selected']['msg']}", YELLOW)
        sprintMessage(3, 6, f"{wizards[current_wizard]['selected']['msg']}", (ARENA_COLUMNS * 2) - 10)

def render_info_arena():
    global current_wizard, wizards
    pygame.draw.rect(screen, BLUE, (0, 0, SCREEN_WIDTH, SCREEN_HEIGHT))
    pygame.draw.rect(screen, BLACK, (BORDER_WIDTH // 2 , BORDER_WIDTH // 2, ARENA_WIDTH + BORDER_WIDTH, ARENA_HEIGHT + BORDER_WIDTH))
    border(screen, CYAN)    

    selection = select_at(cursor_pos[0], cursor_pos[1])
    if is_wizard(selection):
        stats = {'com': selection['combat'], 'def': selection['defence'], 'rcm': selection['rangedCombat'], 'rng': selection['rangedCombatRange'], 'mov': selection['movement'], 'mnv': selection['manvr'], 'res': selection['magicRes']}
        label = selection['name']
        status = ''
        status = clean_status([key for key, value in selection.items() if value is True and key != 'has_moved' and key != 'illusion'])
    else: 
        stats = get_creature_stats(selection['name'])
        label = clean_label(selection['data']['label'])
        status = clean_status(selection['data']['status'])

    sprint(screen, 3, 1, label, YELLOW)
    sprint(screen, 3, 2, status, GREEN)

    # Static template:
    sprint(screen, 3, 3, 'COMBAT=', CYAN)
    sprint(screen, 14, 3, 'DEFENCE=', CYAN)
    sprint(screen, 3, 4, 'RANGED COMBAT=', CYAN)
    sprint(screen, 20, 4, 'RANGE=', CYAN)
    sprint(screen, 3, 5, 'MOVEMENT ALLOWANCE=', CYAN)
    sprint(screen, 3, 6, 'MANOEUVRE RATING=', CYAN)
    sprint(screen, 3, 7, 'MAGIC RESISTANCE=', CYAN)
    if is_wizard(selection):
        sprint(screen, 3, 8, 'ABILITY=', CYAN)
        sprint(screen, 3, 9, 'SPELLS=', CYAN)

    # Values:
    sprint(screen, 10, 3, f"{stats['com']}", YELLOW)
    sprint(screen, 22, 3, f"{stats['def']}", YELLOW)
    sprint(screen, 17, 4, f"{stats['rcm']}", YELLOW)
    sprint(screen, 26, 4, f"{stats['rng']}", YELLOW)
    sprint(screen, 22, 5, f"{stats['mov']}", YELLOW)
    sprint(screen, 20, 6, f"{stats['mnv']}", YELLOW)
    sprint(screen, 20, 7, f"{stats['res']}", YELLOW)
    if is_wizard(selection): 
        sprint(screen, 11, 8, f"{selection['ability']}", YELLOW)
        sprint(screen, 10, 9, f"{len(selection['spell_book'])}", YELLOW)

def draw_objects():
    for corpse in corpses:
        (sprite, colour) = corpse['frame_set'][-1]
        sprite_at(screen, corpse['x'], corpse['y'], sprite, colour)

def draw_wizards():
    global start_time
    current_time = pygame.time.get_ticks()
    time_since_start = current_time - start_time

    for i in range (1,num_wizards+1):
        if wizards[i]['mounted']: continue      # Mounted wizards are invisible so we can instead see their mount
        if wizards[i]['frame_set']:
            # animated wizard
            num_frames = len(wizards[i]['frame_set'])
            frame_duration = 1000 // num_frames 
            sprite_index = (time_since_start // frame_duration) % num_frames
            (sprite_name, colour) = wizards[i]['frame_set'][sprite_index]
            if(sprite_name==''): sprite_name = f"character_{wizards[i]['sprite']}_sprite"
            sprite_at(screen, wizards[i]['x'], wizards[i]['y'], sprite_name, colour)
        else:
            # basic wizard
            sprite_at(screen, wizards[i]['x'], wizards[i]['y'], f"character_{wizards[i]['sprite']}_sprite", PALETTE[wizards[i]['palette']])

def draw_creations():
    global start_time, highlightWizard
    current_time = pygame.time.get_ticks()
    num_frames = 4
    frame_duration = 1000 // num_frames  # 4 fps animation

    # Calculate how much time has passed since the start of the animations.
    time_since_start = current_time - start_time
    
    for creation in creations:
        # Determine the current frame for all creations based on the global start_time.
        sprite_index = (time_since_start // frame_duration) % num_frames
        
        (sprite_name, colour) = creation['frame_set'][sprite_index]
        owner_colour = PALETTE[wizards[creation['owner']]['palette']]
    
        if (showBases and not any(s in creation['data']['status'] for s in [F_SPREADS, F_STRUCT, F_TREE]) and not creation['has_moved']) or (current_screen == GS_INSPECT and showBases):
            ellipse = (creation['x'] * TILE_SIZE, (1 + creation['y']) * TILE_SIZE - (TILE_SIZE //4), TILE_SIZE, 3)
            pygame.draw.ellipse(screen, owner_colour, ellipse, 1)
        sprite_at(screen, creation['x'], creation['y'], sprite_name, colour, True)

        if creation['owner'] == highlightWizard:
            sprite_at(screen, creation['x'], creation['y'], CURSOR_FRAME, PALETTE[wizards[highlightWizard]['palette']], True)
    
def draw_cursor():
    global cursor_type, cursor_pos

    if current_screen == GS_INSPECT:
        sprite_at(screen, cursor_pos[0], cursor_pos[1], CURSOR_FRAME, PALETTE[wizards[current_wizard]['palette']], True)
    elif get_distance([cursor_pos[0], cursor_pos[1]],[wizards[current_wizard]['x'], wizards[current_wizard]['y']]) > 0:
        sprite_at(screen, cursor_pos[0], cursor_pos[1], (CURSOR_CORNER if rangedCombatTime else cursor_type ), PALETTE[wizards[current_wizard]['palette']], True)
    else:
        sprite_at(screen, cursor_pos[0], cursor_pos[1], (CURSOR_CORNER if rangedCombatTime else cursor_type ), PALETTE[wizards[current_wizard]['palette']], True)


def run_animations_and_creations():
    global animations, creations, newCreations
    # These animations should be blocking by design i.e. input frozen etc.

    def get_point_from_percent(start_point, end_point, n):
        """
        Calculate the point that is n percent along the line defined by start_point and end_point.

        :param start_point: A tuple (x0, y0) representing the starting point of the line.
        :param end_point: A tuple (x1, y1) representing the end point of the line.
        :param n: A float representing the percentage along the line (0 <= n <= 99).
        :return: A tuple (x, y) representing the point n percent along the line.
        """
        n = max(0, min(n, 99)) / 100.0

        x0, y0 = start_point
        x1, y1 = end_point

        # Calculate the x and y coordinates of the point n percent along the line
        x = x0 + (x1 - x0) * n
        y = y0 + (y1 - y0) * n

        return int(x), int(y)
   
    if animations: animation = animations.pop()

    if 'dest_x' in animation: # it's beam
        startPos = ( (animation['x'] * TILE_SIZE) + TILE_SIZE // 2 , (animation['y'] * TILE_SIZE) + TILE_SIZE // 2 )
        endPos = ( (animation['dest_x'] * TILE_SIZE) + TILE_SIZE // 2 , (animation['dest_y'] * TILE_SIZE) + TILE_SIZE // 2 )
        newPos = startPos
        distance = get_distance([animation['x'], animation['y']], [animation['dest_x'], animation['dest_y']])
        print(f"Beam rate {animation['rate']} across distance {distance}")
        
        for i in range(0, 100, 3):
            newPos = get_point_from_percent(startPos, endPos, i)
            sprite_at(screen, animation['dest_x'], animation['dest_y'], 'nothingsprite', BLACK, False)
            pygame.draw.circle(screen, animation['colour'], newPos, 1, 0)

            clock.tick(300)
            pygame.transform.smoothscale(screen, (RENDER_WIDTH, RENDER_HEIGHT), main_screen)
            pygame.display.flip()

    else:
        for frame in animation['frame_set']:
            (sprite, colour) = frame
            sprite_at(screen, animation['x'], animation['y'], sprite, colour)

            clock.tick(animation['rate'])
            pygame.transform.smoothscale(screen, (RENDER_WIDTH, RENDER_HEIGHT), main_screen)
            pygame.display.flip()
        
    if newCreations: creations.append(newCreations.pop())

    return

def render_winner():
    pygame.draw.rect(screen, BLACK, (BORDER_WIDTH, BORDER_WIDTH, ARENA_WIDTH, ARENA_HEIGHT))
    colour_duration = 1000 # ms
    flashColourIndex = (pygame.time.get_ticks() // colour_duration) % len(PALETTE[1:]) # Not black

    flashColour = PALETTE[1:][flashColourIndex] # Not black
    border(screen, flashColour)

    draw_objects()
    draw_wizards()
    draw_creations()

    survivingWizards = [w for w in wizards if w['defeated'] is False]
    midRow = (ARENA_ROWS // 2) + 1
    numWinners = len(survivingWizards)
    alignmentChar = get_alignment_character(worldAlignment).replace('-','#')
   
    sprint(screen,0,ARENA_ROWS + 1.5, "PRESS ANY KEY ", YELLOW, True)

    sprint(screen, 7, midRow - numWinners - 2, f"{(alignmentChar * 6)} {'WINNER' if numWinners == 1 else '  DRAW  '} {(alignmentChar * 6)}", flashColour)
    sprint(screen, 7, midRow - numWinners - 1, alignmentChar + (' ' * 18) + alignmentChar, flashColour)
    
    for i in range(0,numWinners):
        wizardPalette = hex(survivingWizards[i]['palette'])[2:]
        sprint(screen, 7, midRow - numWinners + i, alignmentChar + ' ' * 18 + alignmentChar, flashColour)
        sprint(screen, 12, midRow - numWinners + i, survivingWizards[i]['name'], PALETTE[survivingWizards[i]['palette']])     # Winner names

    sprint(screen, 7, midRow - numWinners + 1, alignmentChar + (' ' * 18) + alignmentChar, flashColour)
    sprint(screen, 7, midRow - numWinners + 2, f"{(alignmentChar * 20)}", flashColour)

def render_arena():
    global messageText, creations, newCreations
    pygame.draw.rect(screen, BLACK, (BORDER_WIDTH, BORDER_WIDTH, ARENA_WIDTH, ARENA_HEIGHT))
    border(screen,PALETTE[wizards[current_wizard]['palette']])
    for x in range(0, ARENA_WIDTH, TILE_SIZE):
        for y in range(0, ARENA_HEIGHT, TILE_SIZE):
            pygame.draw.rect(screen, (24,24,24), (BORDER_WIDTH + x, BORDER_WIDTH + y, TILE_SIZE, TILE_SIZE), 1)
    
    draw_objects()
    draw_wizards()
    draw_creations()
    draw_cursor()
    if animations: run_animations_and_creations()
    if dismount_checking: messageText = "DISMOUNT WIZARD? (Y OR N)"
    if messageText: sprint(screen, 1, ARENA_ROWS + 1.5, messageText, YELLOW)

def render():
    global current_screen
    screen.fill(BLACK)
    play_sound()
    if current_screen == GS_SETUP:                                                                  render_setup()
    elif current_screen == GS_GAME_OVER:                                                            render_winner()            
    elif current_screen == GS_NAME:                                                                 render_name()
    elif current_screen == GS_MENU:                                                                 render_menu()
    elif current_screen == GS_SELECT:                                                               render_select()
    elif current_screen == GS_CAST or current_screen == GS_ARENA or current_screen == GS_INSPECT:   render_arena()
    elif current_screen == GS_INFO:                                                                 render_info()
    elif current_screen == GS_INFO_ARENA:                                                           render_info_arena()  
    elif current_screen == GS_ARENA:                                                                render_arena()   
    else:  # current_screen = GS_INTRO or something else
        current_screen = GS_INTRO # Catch the something else ;)
        render_intro()

def game_loop():
    running = True
    while running:
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                running = False
            handle_input(event)
        render()
        # Stretch and blit the buffer to the main screen
        clock.tick(30)
        pygame.transform.smoothscale(screen, (RENDER_WIDTH, RENDER_HEIGHT), main_screen)
        pygame.display.flip()

if __name__ == '__main__':
    game_loop()
    pygame.quit()

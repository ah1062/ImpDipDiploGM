import asyncio
import logging
import os
import random
import time
from random import randrange
from typing import Callable
from scipy.integrate import odeint

from black.trans import defaultdict
from discord import (
    CategoryChannel,
    Member,
    Role,
    HTTPException,
    NotFound,
    TextChannel,
    Thread,
)
from discord import PermissionOverwrite
from discord.ext import commands
from discord.utils import find as discord_find

from bot import config
import bot.perms as perms
from bot.config import is_bumble, temporary_bumbles, ERROR_COLOUR
from bot.parse_edit_state import parse_edit_state
from bot.parse_order import parse_order, parse_remove_order
from bot.utils import (
    get_channel_by_player,
    get_filtered_orders,
    get_orders,
    get_orders_log,
    get_player_by_channel,
    get_player_by_name,
    is_gm,
    send_message_and_file,
    get_role_by_player,
    log_command,
    fish_pop_model,
)
from diplomacy.adjudicator.utils import svg_to_png
from diplomacy.persistence import phase
from diplomacy.persistence.db.database import get_connection
from diplomacy.persistence.manager import Manager
from diplomacy.persistence.order import Build, Disband
from diplomacy.persistence.player import Player

import re

logger = logging.getLogger(__name__)

ping_text_choices = [
    "proudly states",
    "fervently believes in the power of",
    "is being mind controlled by",
]
color_options = {"standard", "dark", "pink", "blue", "kingdoms", "empires"}


async def ping(ctx: commands.Context, _: Manager) -> None:
    response = "Beep Boop"
    if random.random() < 0.1:
        author = ctx.message.author
        content = ctx.message.content.removeprefix(ctx.prefix + ctx.invoked_with)
        if content == "":
            content = " nothing"
        name = author.nick
        if not name:
            name = author.name
        response = name + " " + random.choice(ping_text_choices) + content
    await send_message_and_file(channel=ctx.channel, title=response)


async def pelican(ctx: commands.Context, manager: Manager) -> None:
    pelican_places = {
        "your home": 15,
        "a kebab store": 12,
        "a jungle": 10,
        "a cursed IKEA": 10,
        "a supermarket": 9,
        "Formosa": 8,
        "the Vatican at night": 7,
        "your dreams": 5,
        "a german bureaucracy office": 5,
        "a karaoke bar in Tokyo": 5,
        "a quantum physics lecture": 4,
        "your own mind": 3,
        "Area 51": 2,
        "the Teletubbies’ homeland": 0.9,
        "Summoners’ Rift": 0.1,
    }
    chosen_place = random.choices(
        list(pelican_places.keys()), weights=list(pelican_places.values()), k=1
    )[0]
    message = f"A pelican is chasing you through {chosen_place}!"
    await send_message_and_file(channel=ctx.channel, title=message)


async def bumble(ctx: commands.Context, manager: Manager) -> None:
    list_of_bumble = list("bumble")
    random.shuffle(list_of_bumble)
    word_of_bumble = "".join(list_of_bumble)

    if is_bumble(ctx.author.name) and random.randrange(0, 10) == 0:
        word_of_bumble = "bumble"

    if word_of_bumble == "bumble":
        word_of_bumble = "You are the chosen bumble"

        if ctx.author.name not in temporary_bumbles:
            # no keeping temporary bumbleship easily
            temporary_bumbles.add(ctx.author.name)
    if word_of_bumble == "elbmub":
        word_of_bumble = "elbmub nesohc eht era uoY"

    board = manager.get_board(ctx.guild.id)
    board.fish -= 1
    await send_message_and_file(channel=ctx.channel, title=word_of_bumble)


async def fish(ctx: commands.Context, manager: Manager) -> None:
    board = manager.get_board(ctx.guild.id)
    fish_num = random.randrange(0, 20)

    # overfishing model
    # https://www.maths.gla.ac.uk/~nah/2J/ch1.pdf
    # figure 1.9
    growth_rate = 0.001
    carrying_capacity = 1000
    args = (growth_rate, carrying_capacity)

    time_now = time.time()
    delta_t = time_now - board.fish_pop["time"]


    board.fish_pop["time"] = time_now
    board.fish_pop["fish_pop"] = odeint(
        fish_pop_model, board.fish_pop["fish_pop"], [0, delta_t], args=args
    )[1]

    if board.fish_pop["fish_pop"] <= 200:
        fish_num += 5
    if board.fish_pop["fish_pop"] <= 50:
        fish_num += 20

    debumblify = False
    if is_bumble(ctx.author.name) and random.randrange(0, 10) == 0:
        # Bumbles are good fishers
        if fish_num == 1:
            fish_num = 0
        elif fish_num > 15:
            fish_num -= 5

    if 0 == fish_num:
        # something special
        rare_fish_options = [
            ":dolphin:",
            ":shark:",
            ":duck:",
            ":goose:",
            ":dodo:",
            ":flamingo:",
            ":penguin:",
            ":unicorn:",
            ":swan:",
            ":whale:",
            ":seal:",
            ":sheep:",
            ":sloth:",
            ":hippopotamus:",
        ]
        board.fish += 10
        board.fish_pop["fish_pop"] -= 10
        fish_message = f"**Caught a rare fish!** {random.choice(rare_fish_options)}"
    elif fish_num < 16:
        fish_num = (fish_num + 1) // 2
        board.fish += fish_num
        board.fish_pop["fish_pop"] -= fish_num
        fish_emoji_options = [
            ":fish:",
            ":tropical_fish:",
            ":blowfish:",
            ":jellyfish:",
            ":shrimp:",
        ]
        fish_weights = [8, 4, 2, 1, 2]
        fish_message = f"Caught {fish_num} fish! " + " ".join(
            random.choices(fish_emoji_options, weights=fish_weights, k=fish_num)
        )
    elif fish_num < 21:
        fish_num = (21 - fish_num) // 2

        if is_bumble(ctx.author.name):
            if randrange(0, 20) == 0:
                # Sometimes Bumbles are so bad at fishing they debumblify
                debumblify = True
                fish_num = randrange(10, 20)
                return
            else:
                # Bumbles that lose fish lose a lot of them
                fish_num *= randrange(3, 10)

        board.fish -= fish_num
        board.fish_pop["fish_pop"] += fish_num
        fish_kind = "captured" if board.fish >= 0 else "future"
        fish_message = f"Accidentally let {fish_num} {fish_kind} fish sneak away :("
    else:
        fish_message = f"You find nothing but barren water and overfished seas, maybe let the population recover?"
    fish_message += f"\nIn total, {board.fish} fish have been caught!"
    if random.randrange(0, 5) == 0:
        get_connection().execute_arbitrary_sql(
            """UPDATE boards SET fish=? WHERE board_id=? AND phase=?""",
            (board.fish, board.board_id, board.get_phase_and_year_string()),
        )

    if debumblify:
        temporary_bumbles.remove(ctx.author.name)
        fish_message = f"\n Your luck has run out! {fish_message}\nBumble is sad, you must once again prove your worth by Bumbling!"

    await send_message_and_file(channel=ctx.channel, title=fish_message)


async def global_leaderboard(ctx: commands.Context, manager: Manager) -> None:
    sorted_boards = sorted(
        manager._boards.items(), key=lambda board: board[1].fish, reverse=True
    )
    raw_boards = tuple(map(lambda b: b[1], sorted_boards))
    try:
        this_board = manager.get_board(ctx.guild.id)
    except:
        this_board = None
    sorted_boards = sorted_boards[:9]
    text = ""
    if this_board is not None:
        index = str(raw_boards.index(this_board) + 1)
    else:
        index = "NaN"

    max_fishes = len(str(sorted_boards[0][1].fish))

    for i, board in enumerate(sorted_boards):
        bold = "**" if this_board == board[1] else ""
        guild = ctx.bot.get_guild(board[0])
        if guild:
            text += f"\\#{i + 1: >{len(index)}} | {board[1].fish: <{max_fishes}} | {bold}{guild.name}{bold}\n"
    if this_board is not None and this_board not in raw_boards[:9]:
        text += f"\n\\#{index} | {this_board.fish: <{max_fishes}} | {ctx.guild.name}"

    await send_message_and_file(
        channel=ctx.channel, title="Global Fishing Leaderboard", message=text
    )


async def phish(ctx: commands.Context, _: Manager) -> None:
    message = "No! Phishing is bad!"
    if is_bumble(ctx.author.name):
        message = "Please provide your firstborn pet and your soul for a chance at winning your next game!"
    await send_message_and_file(channel=ctx.channel, title=message)


async def cheat(ctx: commands.Context, manager: Manager) -> None:
    message = "Cheating is disabled for this user."
    author = ctx.message.author.name
    board = manager.get_board(ctx.guild.id)
    if is_bumble(author):
        sample = random.choice(
            [
                f"It looks like {author} is getting coalitioned this turn :cry:",
                f"{author} is talking about stabbing {random.choice(list(board.players)).name} again",
                f"looks like he's throwing to {author}... shame",
                "yeah",
                "People in this game are not voiding enough",
                f"I can't believe {author} is moving to {random.choice(list(board.provinces)).name}",
                f"{author} has a bunch of invalid orders",
                f"No one noticed that {author} overbuilt?",
                f"{random.choice(list(board.players)).name} is in a perfect position to stab {author}",
                ".bumble",
            ]
        )
        message = (
            f'Here\'s a helpful message I stole from the spectator chat: \n"{sample}"'
        )
    await send_message_and_file(channel=ctx.channel, title=message)


async def advice(ctx: commands.Context, _: Manager) -> None:
    message = "You are not worthy of advice."
    if is_bumble(ctx.author.name):
        message = "Bumble suggests that you go fishing, although typically blasphemous, today is your lucky day!"
    elif randrange(0, 5) == 0:
        message = random.choice(
            [
                "Bumble was surprised you asked him for advice and wasn't ready to give you any, maybe if you were a true follower...",
                "Icecream demands that you void more and will not be giving any advice until sated.",
                "Salt suggests that stabbing all of your neighbors is a good play in this particular situation.",
                "Ezio points you to an ancient proverb: see dot take dot.",
                "CaptainMeme advises balance of power play at this instance.",
                "Ash Lael deems you a sufficiently apt liar, go use those skills!",
                "Kwiksand suggests winning.",
                "Ambrosius advises taking the opportunity you've been considering, for more will ensue.",
                "The GMs suggest you input your orders so they don't need to hound you for them at the deadline.",
            ]
        )
    await send_message_and_file(channel=ctx.channel, title=message)


async def botsay(ctx: commands.Context, _: Manager) -> None:
    # noinspection PyTypeChecker
    if len(ctx.message.channel_mentions) == 0:
        await send_message_and_file(
            channel=ctx.channel,
            title="Error",
            message="No Channel Given",
            embed_colour=ERROR_COLOUR,
        )
        return
    channel = ctx.message.channel_mentions[0]
    content = ctx.message.content.removeprefix(ctx.prefix + ctx.invoked_with)
    content = content.replace(channel.mention, "").strip()
    if len(content) == 0:
        await send_message_and_file(
            channel=ctx.channel,
            title="Error",
            message="No Message Given",
            embed_colour=ERROR_COLOUR,
        )
        return

    message = await send_message_and_file(channel=channel, message=content)
    log_command(logger, ctx, f"Sent Message into #{channel.name}")
    await send_message_and_file(
        channel=ctx.channel,
        title=f"Sent Message",
        message=message.jump_url,
    )


async def announce(ctx: commands.Context, manager: Manager) -> None:
    guilds_with_games = manager.list_servers()
    content = ctx.message.content.removeprefix(ctx.prefix + ctx.invoked_with)
    content = re.sub(r'<@&[0-9]{16,20}>', r'{}', content)
    roles = list(map(lambda role: role.name, ctx.message.role_mentions))
    message = ""
    for server in ctx.bot.guilds:
        if server is None:
            continue
        admin_chat_channel = next(channel for channel in server.channels if is_gm_channel(channel))
        if admin_chat_channel is None:
            message += f"\n- ~~{server.name}~~ Couldn't find admin channel"

        message += f"\n- {server.name}"
        if server.id in guilds_with_games:
            board = manager.get_board(server.id)
            message += f" - {board.phase.name} {board.get_year_str()}"
        else:
            message += f" - no active game"

        server_roles = []
        for role_name in roles:
            for role in server.roles:
                if role.name == role_name:
                    server_roles.append(role.mention)
                    break
            else:
                server_roles.append(role_name)

        if len(server_roles) > 0:
            await admin_chat_channel.send(("||" + "{}" * len(server_roles) + "||").format(*server_roles))
        await send_message_and_file(
            channel=admin_chat_channel,
            title="Admin Announcement",
            message=content.format(*server_roles)
        )
    log_command(logger, ctx, f"Sent Announcement into {len(ctx.bot.guilds)} servers")
    await send_message_and_file(
        channel=ctx.channel,
        title=f"Announcement sent to {len(ctx.bot.guilds)} servers:",
        message=message
    )


async def servers(ctx: commands.Context, manager: Manager) -> None:
    servers_with_games = manager.list_servers()
    message = ""
    for server in ctx.bot.guilds:
        if server is None:
            continue

        channels = server.channels
        for channel in channels:
            if isinstance(channel, TextChannel):
                break
        else:
            message += f"\n- {server.name} - Could not find a channel for invite"
            continue

        if server.id in servers_with_games:
            servers_with_games.remove(server.id)
            board = manager.get_board(server.id)
            board_state = f" - {board.phase.name} {board.get_year_str()}"
        else:
            board_state = f" - no active game"

        try:
            invite = await channel.create_invite(max_age=300)
        except (HTTPException, NotFound):
            message += f"\n- {server.name} - Could not create invite"
        else:
            message += f"\n- [{server.name}](<{invite.url}>)"

        message += board_state

    # Servers with games the bot is not in
    if servers_with_games:
        message += f"\n There is a further {len(servers_with_games)} games in servers I am no longer in"

    log_command(logger, ctx, f"Found {len(ctx.bot.guilds)} servers")
    await send_message_and_file(
        channel=ctx.channel, title=f"{len(ctx.bot.guilds)} Servers", message=message
    )



async def bulk_allocate_role(ctx: commands.Context, manager: Manager) -> None:
    guild = ctx.guild
    if guild is None:
        return

    # extract roles to be allocated based off of mentions
    # .bulk_allocate_role <@B1.4 Player> <@B1.4 GM Team> ...
    roles = ctx.message.role_mentions
    role_names = list(map(lambda r: r.name, roles))
    if len(roles) == 0:
        await send_message_and_file(channel=ctx.channel, title="Error", message="No roles were supplied to allocate. Please include a role mention in the command.")
        return

    # parse usernames from trailing contents
    # .bulk_allocate_role <@B1.4 Player> elisha thisisflare kingofprussia ...
    content = ctx.message.content.removeprefix(ctx.prefix + ctx.invoked_with)

    usernames = []
    components = content.split(" ")
    for comp in components:
        if comp == "":
            continue

        match = re.match(r"<@&\d+>", comp)
        if match:
            continue

        usernames.append(comp)

    success_count = 0
    failed = []
    skipped = []
    for user in usernames:
        # FIND USER FROM USERNAME
        member = discord_find(
            lambda m: m.name == user,
            guild.members,
        )

        if not member or member is None:
            failed.append((user, "Member not Found"))
            continue

        for role in roles:
            if role in member.roles:
                skipped.append((user, f"already had role @{role.name}"))
                continue

            try:
                await member.add_roles(role)
                success_count += 1
            except Exception as e:
                failed.append((user, f"Error Adding Role- {e}"))

    failed_out = "\n".join([f"{u}: {m}" for u, m in failed])
    skipped_out = "\n".join([f"{u}: {m}" for u, m in skipped])
    out = (
        f"Allocated Roles {', '.join(role_names)} to {len(usernames)} users.\n"
        + f"Succeeded in applying a role {success_count} times.\n"
        + f"Failed {len(failed)} times.\n"
        + f"Skipped {len(skipped)} times for already having the role.\n"
        + "----\n"
        + f"Failed Reasons:\n{failed_out}\n"
        + "----\n"
        + f"Skipped Reasons:\n{skipped_out}\n"
        + "----\n"
    )

    await send_message_and_file(
        channel=ctx.channel, title="Wave Allocation Info", message=out
    )


@perms.player("order")
async def order(player: Player | None, ctx: commands.Context, manager: Manager) -> None:
    board = manager.get_board(ctx.guild.id)

    if player and not board.orders_enabled:
        log_command(logger, ctx, f"Orders locked - not processing")
        await send_message_and_file(
            channel=ctx.channel,
            title="Orders locked!",
            message="If you think this is an error, contact a GM.",
            embed_colour=ERROR_COLOUR,
        )
        return

    message = parse_order(ctx.message.content, player, board)
    if "title" in message:
        log_command(logger, ctx, message=message["title"])
    elif "message" in message:
        log_command(logger, ctx, message=message["message"][:100])
    elif "messages" in message and len(message["messages"]) > 0:
        log_command(logger, ctx, message=message["messages"][0][:100])
    await send_message_and_file(channel=ctx.channel, **message)


@perms.player("remove orders")
async def remove_order(
    player: Player | None, ctx: commands.Context, manager: Manager
) -> None:
    board = manager.get_board(ctx.guild.id)

    if player and not board.orders_enabled:
        log_command(logger, ctx, f"Orders locked - not processing")
        await send_message_and_file(
            channel=ctx.channel,
            title="Orders locked!",
            message="If you think this is an error, contact a GM.",
            embed_colour=ERROR_COLOUR,
        )
        return

    content = ctx.message.content.removeprefix(ctx.prefix + ctx.invoked_with)

    message = parse_remove_order(content, player, board)
    log_command(logger, ctx, message=message["message"])
    await send_message_and_file(channel=ctx.channel, **message)


@perms.player("view orders")
async def view_orders(player: Player | None, ctx: commands.Context, manager: Manager) -> None:
    arguments = ctx.message.content.removeprefix(ctx.prefix + ctx.invoked_with).strip().lower().split()
    subset = "missing" if {"missing", "miss", "m"} & set(arguments) else None
    subset = "submitted" if {"submitted", "submit", "sub", "s"} & set(arguments) else subset

    try:
        board = manager.get_board(ctx.guild.id)
        order_text = get_orders(board, player, ctx, subset=subset)
    except RuntimeError as err:
        logger.error(err, exc_info=True)
        log_command(logger, ctx, message=f"Failed for an unknown reason", level=logging.ERROR)
        await send_message_and_file(channel=ctx.channel,
                                    title="Unknown Error: Please contact your local bot dev",
                                    embed_colour=ERROR_COLOUR)
        return
    log_command(logger, ctx, message=f"Success - generated orders for {board.phase.name} {board.get_year_str()}")
    await send_message_and_file(channel=ctx.channel,
                                title=f"{board.phase.name} {board.get_year_str()}",
                                message=order_text)


async def publish_orders(ctx: commands.Context, manager: Manager) -> None:
    board = manager.get_previous_board(ctx.guild.id)
    if not board:
        await send_message_and_file(
            channel=ctx.channel,
            title="Failed to get previous phase",
            embed_colour=ERROR_COLOUR,
        )
        return

    try:
        order_text = get_orders(board, None, ctx, fields=True)
    except RuntimeError as err:
        logger.error(err, exc_info=True)
        log_command(
            logger, ctx, message=f"Failed for an unknown reason", level=logging.ERROR
        )
        await send_message_and_file(
            channel=ctx.channel,
            title="Unknown Error: Please contact your local bot dev",
            embed_colour=ERROR_COLOUR,
        )
        return
    orders_log_channel = get_orders_log(ctx.guild)
    if not orders_log_channel:
        log_command(
            logger,
            ctx,
            message=f"Could not find orders log channel",
            level=logging.WARN,
        )
        await send_message_and_file(
            channel=ctx.channel,
            title="Could not find orders log channel",
            embed_colour=ERROR_COLOUR,
        )
        return
    else:
        await send_message_and_file(
            channel=orders_log_channel,
            title=f"{board.phase.name} {board.get_year_str()}",
            fields=order_text,
        )
        log_command(logger, ctx, message=f"Successfully published orders")
        await send_message_and_file(
            channel=ctx.channel, title=f"Sent Orders to {orders_log_channel.mention}"
        )


@perms.player("view map")
async def view_map(
    player: Player | None, ctx: commands.Context, manager: Manager
) -> dict[str, ...]:
    arguments = (
        ctx.message.content.removeprefix(ctx.prefix + ctx.invoked_with)
        .strip()
        .lower()
        .split()
    )
    convert_svg = player or not ({"true", "t", "svg", "s"} & set(arguments))
    color_arguments = list(color_options & set(arguments))
    color_mode = color_arguments[0] if color_arguments else None
    board = manager.get_board(ctx.guild.id)

    if player and not board.orders_enabled:
        log_command(logger, ctx, f"Orders locked - not processing")
        await send_message_and_file(
            channel=ctx.channel,
            title="Orders locked!",
            message="If you think this is an error, contact a GM.",
            embed_colour=ERROR_COLOUR,
        )
        return

    try:
        if not board.fow:
            file, file_name = manager.draw_moves_map(ctx.guild.id, player, color_mode)
        else:
            file, file_name = manager.draw_fow_players_moves_map(
                ctx.guild.id, player, color_mode
            )
    except Exception as err:
        logger.error(err, exc_info=True)
        log_command(
            logger,
            ctx,
            message=f"Failed to generate map for an unknown reason",
            level=logging.ERROR,
        )
        await send_message_and_file(
            channel=ctx.channel,
            title="Unknown Error: Please contact your local bot dev",
            embed_colour=ERROR_COLOUR,
        )
        return
    log_command(
        logger,
        ctx,
        message=f"Generated moves map for {board.phase.name} {board.get_year_str()}",
    )
    await send_message_and_file(
        channel=ctx.channel,
        title=f"{board.phase.name} {board.get_year_str()}",
        file=file,
        file_name=file_name,
        convert_svg=convert_svg,
        file_in_embed=False,
    )


@perms.player("view current")
async def view_current(
    player: Player | None, ctx: commands.Context, manager: Manager
) -> None:
    arguments = (
        ctx.message.content.removeprefix(ctx.prefix + ctx.invoked_with)
        .strip()
        .lower()
        .split()
    )
    convert_svg = not ({"true", "t", "svg", "s"} & set(arguments))
    color_arguments = list(color_options & set(arguments))
    color_mode = color_arguments[0] if color_arguments else None
    board = manager.get_board(ctx.guild.id)

    if player and not board.orders_enabled:
        log_command(logger, ctx, f"Orders locked - not processing")
        await send_message_and_file(
            channel=ctx.channel,
            title="Orders locked!",
            message="If you think this is an error, contact a GM.",
            embed_colour=ERROR_COLOUR,
        )
        return

    try:
        if not board.fow:
            file, file_name = manager.draw_current_map(ctx.guild.id, color_mode)
        else:
            file, file_name = manager.draw_fow_current_map(
                ctx.guild.id, player, color_mode
            )
    except Exception as err:
        logger.error(err, exc_info=True)
        log_command(
            logger,
            ctx,
            message=f"Failed to generate map for an unknown reason",
            level=logging.ERROR,
        )
        await send_message_and_file(
            channel=ctx.channel,
            title="Unknown Error: Please contact your local bot dev",
            embed_colour=ERROR_COLOUR,
        )
        return
    log_command(
        logger,
        ctx,
        message=f"Generated current map for {board.phase.name} {board.get_year_str()}",
    )
    await send_message_and_file(
        channel=ctx.channel,
        title=f"{board.phase.name} {board.get_year_str()}",
        file=file,
        file_name=file_name,
        convert_svg=convert_svg,
        file_in_embed=False,
    )


@perms.player("view gui")
async def view_gui(
    player: Player | None, ctx: commands.Context, manager: Manager
) -> None:
    arguments = (
        ctx.message.content.removeprefix(ctx.prefix + ctx.invoked_with)
        .strip()
        .lower()
        .split()
    )
    color_arguments = list(color_options & set(arguments))
    color_mode = color_arguments[0] if color_arguments else None
    board = manager.get_board(ctx.guild.id)

    if player and not board.orders_enabled:
        log_command(logger, ctx, f"Orders locked - not processing")
        await send_message_and_file(
            channel=ctx.channel,
            title="Orders locked!",
            message="If you think this is an error, contact a GM.",
            embed_colour=ERROR_COLOUR,
        )
        return

    try:
        if not board.fow:
            file, file_name = manager.draw_gui_map(ctx.guild.id, color_mode)
        else:
            file, file_name = manager.draw_fow_gui_map(ctx.guild.id, player, color_mode)
    except Exception as err:
        log_command(
            logger,
            ctx,
            message=f"Failed to generate map for an unknown reason",
            level=logging.ERROR,
        )
        await send_message_and_file(
            channel=ctx.channel,
            title="Unknown Error: Please contact your local bot dev",
            embed_colour=ERROR_COLOUR,
        )
        raise err
        return
    log_command(
        logger,
        ctx,
        message=f"Generated current map for {board.phase.name} {board.get_year_str()}",
    )
    await send_message_and_file(
        channel=ctx.channel,
        title=f"{board.phase.name} {board.get_year_str()}",
        file=file,
        file_name=file_name,
        convert_svg=False,
        file_in_embed=False,
    )



async def adjudicate(ctx: commands.Context, manager: Manager) -> None:
    board = manager.get_board(ctx.guild.id)

    arguments = (
        ctx.message.content.removeprefix(ctx.prefix + ctx.invoked_with)
        .strip()
        .lower()
        .split()
    )
    return_svg = not ({"true", "t", "svg", "s"} & set(arguments))
    color_arguments = list(color_options & set(arguments))
    color_mode = color_arguments[0] if color_arguments else None
    # await send_message_and_file(channel=ctx.channel, **await view_map(ctx, manager))
    # await send_message_and_file(channel=ctx.channel, **await view_orders(ctx, manager))
    manager.adjudicate(ctx.guild.id)

    file, file_name = manager.draw_current_map(ctx.guild.id, color_mode)

    log_command(
        logger,
        ctx,
        message=f"Adjudication Sucessful for {board.phase.name} {board.get_year_str()}",
    )
    await send_message_and_file(
        channel=ctx.channel,
        title=f"{board.phase.name} {board.get_year_str()}",
        message="Adjudication has completed successfully",
        file=file,
        file_name=file_name,
        convert_svg=return_svg,
        file_in_embed=False,
    )



async def rollback(ctx: commands.Context, manager: Manager) -> None:
    message = manager.rollback(ctx.guild.id)
    log_command(logger, ctx, message=message["message"])
    await send_message_and_file(channel=ctx.channel, **message)


async def reload(ctx: commands.Context, manager: Manager) -> None:
    message = manager.reload(ctx.guild.id)
    log_command(logger, ctx, message=message["message"])
    await send_message_and_file(channel=ctx.channel, **message)


async def remove_all(ctx: commands.Context, manager: Manager) -> None:
    board = manager.get_board(ctx.guild.id)
    for unit in board.units:
        unit.order = None

    database = get_connection()
    database.save_order_for_units(board, board.units)
    log_command(logger, ctx, message="Removed all Orders")
    await send_message_and_file(channel=ctx.channel, title="Removed all Orders")


async def get_scoreboard(ctx: commands.Context, manager: Manager) -> None:
    board = manager.get_board(ctx.guild.id)

    if board.fow:
        perms.assert_gm_only(ctx, "get scoreboard")

    the_player = perms.get_player_by_context(ctx, manager)

    response = ""
    if board.is_chaos() and not "standard" in ctx.message.content:
        scoreboard_rows = []

        latest_index = -1
        latest_points = float("inf")

        for i, player in enumerate(board.get_players_by_points()):
            points = player.points

            if points < latest_points:
                latest_index = i
                latest_points = points

            if i <= 25 or player == the_player:
                scoreboard_rows.append((latest_index + 1, player))
            elif the_player == None:
                break
            elif the_player == player:
                scoreboard_rows.append((latest_index + 1, player))
                break

        index_length = len(str(scoreboard_rows[-1][0]))
        points_length = len(str(scoreboard_rows[0][1]))

        for index, player in scoreboard_rows:
            response += (
                f"\n\\#{index: >{index_length}} | {player.points: <{points_length}} | **{player.name}**: "
                f"{len(player.centers)} ({'+' if len(player.centers) - len(player.units) >= 0 else ''}"
                f"{len(player.centers) - len(player.units)})"
            )
    else:
        response = ""
        for player in board.get_players_by_score():
            if (player_role := get_role_by_player(player, ctx.guild.roles)) is not None:
                player_name = player_role.mention
            else:
                player_name = player.name

            response += (
                f"\n**{player_name}**: "
                f"{len(player.centers)} ({'+' if len(player.centers) - len(player.units) >= 0 else ''}"
                f"{len(player.centers) - len(player.units)}) [{round(player.score() * 100, 1)}%]"
            )

    log_command(logger, ctx, message="Generated scoreboard")
    await send_message_and_file(
        channel=ctx.channel,
        title=f"{board.phase.name}" + " " + f"{board.get_year_str()}",
        message=response,
    )



async def edit(ctx: commands.Context, manager: Manager) -> None:
    edit_commands = ctx.message.content.removeprefix(
        ctx.prefix + ctx.invoked_with
    ).strip()
    message = parse_edit_state(edit_commands, manager.get_board(ctx.guild.id))
    log_command(logger, ctx, message=message["title"])
    await send_message_and_file(channel=ctx.channel, **message)


async def create_game(ctx: commands.Context, manager: Manager) -> None:
    gametype = ctx.message.content.removeprefix(ctx.prefix + ctx.invoked_with)
    if gametype == "":
        gametype = "impdip.json"
    else:
        gametype = gametype.removeprefix(" ") + ".json"

    message = manager.create_game(ctx.guild.id, gametype)
    log_command(logger, ctx, message=message)
    await send_message_and_file(channel=ctx.channel, message=message)


async def enable_orders(ctx: commands.Context, manager: Manager) -> None:
    board = manager.get_board(ctx.guild.id)
    board.orders_enabled = True
    log_command(logger, ctx, message="Unlocked orders")
    await send_message_and_file(
        channel=ctx.channel,
        title="Unlocked orders",
        message=f"{board.phase.name} {board.get_year_str()}",
    )


async def disable_orders(ctx: commands.Context, manager: Manager) -> None:
    board = manager.get_board(ctx.guild.id)
    board.orders_enabled = False
    log_command(logger, ctx, message="Locked orders")
    await send_message_and_file(
        channel=ctx.channel,
        title="Locked orders",
        message=f"{board.phase.name} {board.get_year_str()}",
    )


async def delete_game(ctx: commands.Context, manager: Manager) -> None:
    manager.total_delete(ctx.guild.id)
    log_command(logger, ctx, message=f"Deleted game")
    await send_message_and_file(channel=ctx.channel, title="Deleted game")



async def info(ctx: commands.Context, manager: Manager) -> None:
    try:
        board = manager.get_board(ctx.guild.id)
    except RuntimeError:
        log_command(logger, ctx, message="No game this this server.")
        await send_message_and_file(
            channel=ctx.channel, title="There is no game this this server."
        )
        return
    log_command(logger, ctx, message=f"Displayed info - {board.get_year_str()}|"
                                     f"{str(board.phase)}|{str(board.datafile)}|"
                                     f"{'Open' if board.orders_enabled else 'Locked'}" )
    await send_message_and_file(channel=ctx.channel,
                                message=(f"Year: {board.get_year_str()}\n"
                                         f"Phase: {str(board.phase)}\n"
                                         f"Orders are {'Open' if board.orders_enabled else 'Locked'}\n"
                                         f"Game Type: {str(board.datafile)}\n"
                                         f"Chaos: {':white_check_mark:' if board.is_chaos() else ':x:'}\n"
                                         f"Fog of War: {':white_check_mark:' if board.fow else ':x:'}"))


async def province_info(ctx: commands.Context, manager: Manager) -> None:
    board = manager.get_board(ctx.guild.id)

    if not board.orders_enabled:
        perms.assert_gm_only(
            ctx,
            "You cannot use .province_info in a non-GM channel while orders are locked.",
            non_gm_alt="Orders locked! If you think this is an error, contact a GM."
        )
        return

    province_name = ctx.message.content.removeprefix(ctx.prefix + ctx.invoked_with).strip()
    if not province_name:
        log_command(logger, ctx, message=f"No province given")
        await send_message_and_file(
            channel=ctx.channel,
            title="No province given",
            message="Usage: .province_info <province>",
        )
        return
    province, coast = board.get_province_and_coast(province_name)
    if province is None:
        log_command(logger, ctx, message=f"Province `{province_name}` not found")
        await send_message_and_file(
            channel=ctx.channel, title=f"Could not find province {province_name}"
        )
        return

    # FOW permissions
    if board.fow:
        player = perms.require_player_by_context(ctx, manager, "get province info")
        if player and not province in board.get_visible_provinces(player):
            log_command(
                logger,
                ctx,
                message=f"Province `{province_name}` hidden by fow to player",
            )
            await send_message_and_file(
                channel=ctx.channel,
                title=f"Province {province.name} is not visible to you",
            )
            return

    # fmt: off
    if not coast:
        out = f"Type: {province.type.name}\n" + \
            f"Coasts: {len(province.coasts)}\n" + \
            f"Owner: {province.owner.name if province.owner else 'None'}\n" + \
            f"Unit: {(province.unit.player.name + ' ' + province.unit.unit_type.name) if province.unit else 'None'}\n" + \
            f"Center: {province.has_supply_center}\n" + \
            f"Core: {province.core.name if province.core else 'None'}\n" + \
            f"Half-Core: {province.half_core.name if province.half_core else 'None'}\n" + \
            f"Adjacent Provinces:\n- " + "\n- ".join(sorted([adjacent.name for adjacent in province.adjacent | province.impassible_adjacent])) + "\n"
    else:
        coast_unit = None
        if province.unit and province.unit.coast == coast:
            coast_unit = province.unit

        out = "Type: COAST\n" + \
            f"Coast Unit: {(coast_unit.player.name + ' ' + coast_unit.unit_type.name) if coast_unit else 'None'}\n" + \
            f"Province Unit: {(province.unit.player.name + ' ' + province.unit.unit_type.name) if province.unit else 'None'}\n" + \
            "Adjacent Provinces:\n" + \
            "- " + \
            "\n- ".join(sorted([adjacent.name for adjacent in coast.get_adjacent_locations()])) + "\n"
    # fmt: on
    log_command(logger, ctx, message=f"Got info for {province_name}")

    # FIXME title should probably include what coast it is.
    await send_message_and_file(channel=ctx.channel, title=province.name, message=out)



async def player_info(ctx: commands.Context, manager: Manager) -> None:
    board = manager.get_board(ctx.guild.id)

    if not board.orders_enabled:
        perms.assert_gm_only(
            ctx,
            "You cannot use .province_info in a non-GM channel while orders are locked.",
            non_gm_alt= "Orders locked! If you think this is an error, contact a GM."
        )
        return

    player_name = ctx.message.content.removeprefix(ctx.prefix + ctx.invoked_with).strip()
    if not player_name:
        log_command(logger, ctx, message=f"No province given")
        await send_message_and_file(
            channel=ctx.channel,
            title="No province given",
            message="Usage: .province_info <player>",
        )
        return

    # HACK: chaos has same name of players as provinces so we exploit that
    province, _ = board.get_province_and_coast(player_name)
    player: Player = board.get_player(province.name.lower())
    if player is None:
        log_command(logger, ctx, message=f"Player `{player}` not found")
        await send_message_and_file(
            channel=ctx.channel, title=f"Could not find player {player_name}"
        )
        return

    # FOW permissions
    if not board.is_chaos():
        await send_message_and_file(
            channel=ctx.channel, title=f"This command only works for chaos"
        )
        return

    # f"Initial/Current/Victory SC Count [Score]: {player.iscc}/{len(player.centers)}/{player.vscc} [{player.score()}%]\n" + \

    # fmt: off
    bullet = "\n- "
    out = f"Color: #{player.render_color}\n" + \
        f"Points: {player.points}\n" + \
        f"Vassals: {', '.join(map(str, player.vassals))}\n" + \
        f"Liege: {player.liege if player.liege else 'None'}\n" + \
        f"Units: {(bullet + bullet.join([unit.location().name for unit in player.units])) if len(player.units) > 0 else 'None'}\n" + \
        f"Centers ({len(player.centers)}): {(bullet + bullet.join([center.name for center in player.centers])) if len(player.centers) > 0 else 'None'}\n"
    # fmt: on
    log_command(logger, ctx, message=f"Got info for player {player}")

    # FIXME title should probably include what coast it is.
    await send_message_and_file(channel=ctx.channel, title=player.name, message=out)


@perms.player("view visible provinces")
async def visible_provinces(
    player: Player | None, ctx: commands.Context, manager: Manager
) -> None:
    board = manager.get_board(ctx.guild.id)

    if not player or not board.fow:
        log_command(logger, ctx, message=f"No fog of war game")
        await send_message_and_file(
            channel=ctx.channel,
            message="This command only works for players in fog of war games.",
            embed_colour=ERROR_COLOUR,
        )
        return

    visible_provinces = board.get_visible_provinces(player)
    log_command(
        logger, ctx, message=f"There are {len(visible_provinces)} visible provinces"
    )
    await send_message_and_file(
        channel=ctx.channel, message=", ".join([x.name for x in visible_provinces])
    )
    return


async def publicize(ctx: commands.Context, manager: Manager) -> None:
    if not is_gm(ctx.message.author):
        raise PermissionError(f"You cannot publicize a void because you are not a GM.")

    channel = ctx.channel
    board = manager.get_board(ctx.guild.id)

    if not board.is_chaos():
        await send_message_and_file(
            channel=channel,
            message="This command only works for chaos games.",
            embed_colour=ERROR_COLOUR,
        )

    player = get_player_by_channel(channel, manager, ctx.guild.id, ignore_catagory=True)

    # TODO hacky
    users = []
    user_permissions: list[tuple[Member, PermissionOverwrite]] = []
    # Find users with access to this channel
    for overwritter, user_permission in channel.overwrites.items():
        if isinstance(overwritter, Member):
            if user_permission.view_channel:
                users.append(overwritter)
                user_permissions.append((overwritter, user_permission))

    # TODO don't hardcode
    staff_role = None
    spectator_role = None
    for role in ctx.guild.roles:
        if role.name == "World Chaos Staff":
            staff_role = role
        elif role.name == "Spectators":
            spectator_role = role

    if not staff_role or not spectator_role:
        return

    if not player or len(users) == 0:
        await send_message_and_file(
            channel=ctx.channel,
            message="Can't find the applicable user.",
            embed_colour=ERROR_COLOUR,
        )
        return

    # Create Thread
    thread: Thread = await channel.create_thread(
        name=f"{player.name.capitalize()} Orders",
        reason=f"Creating Orders for {player.name}",
        invitable=False,
    )
    await thread.send(f"{''.join([u.mention for u in users])} | {staff_role.mention}")

    # Allow for sending messages in thread
    for user, permission in user_permissions:
        permission.send_messages_in_threads = True
        await channel.set_permissions(target=user, overwrite=permission)

    # Add spectators
    spectator_permissions = PermissionOverwrite(view_channel=True, send_messages=False)
    await channel.set_permissions(
        target=spectator_role, overwrite=spectator_permissions
    )

    # Update name
    await channel.edit(name=channel.name.replace("orders", "void"))

    await send_message_and_file(channel=channel, message="Finished publicizing void.")


async def all_province_data(ctx: commands.Context, manager: Manager) -> None:
    board = manager.get_board(ctx.guild.id)

    if not board.orders_enabled:
        perms.assert_gm_only(ctx, "call .all_province_data while orders are locked")

    province_by_owner = defaultdict(list)
    for province in board.provinces:
        owner = province.owner
        if not owner:
            owner = None
        province_by_owner[owner].append(province.name)

    message = ""
    for owner, provinces in province_by_owner.items():
        if owner is None:
            player_name = "None"
        elif (player_role := get_role_by_player(owner, ctx.guild.roles)) is not None:
            player_name = player_role.mention
        else:
            player_name = owner

        message += f"{player_name}: "
        for province in provinces:
            message += f"{province}, "
        message += "\n\n"

    log_command(
        logger,
        ctx,
        message=f"Found {sum(map(len, province_by_owner.values()))} provinces",
    )
    await send_message_and_file(channel=ctx.channel, message=message)


# needed due to async
from bot.utils import is_gm_channel


# for fog of war
async def publish_fow_current(ctx: commands.Context, manager: Manager):
    await publish_map(
        ctx, manager, "starting map", lambda m, s, p: m.draw_fow_current_map(s, p)
    )



async def publish_fow_moves(ctx: commands.Context, manager: Manager,):
    board = manager.get_board(ctx.guild.id)

    if not board.fow:
        raise ValueError("This is not a fog of war game")

    filter_player = board.get_player(
        ctx.message.content.removeprefix(ctx.prefix + ctx.invoked_with).strip()
    )

    await publish_map(
        ctx,
        manager,
        "moves map",
        lambda m, s, p: m.draw_fow_moves_map(s, p),
        filter_player,
    )


# FIXME add a decorator / helper method for iterating over all player order channels
async def publish_map(
    ctx: commands.Context,
    manager: Manager,
    name: str,
    map_caller: Callable[[Manager, int, Player], tuple[str, str]],
    filter_player=None,
):
    player_category = None

    guild = ctx.guild
    guild_id = guild.id
    board = manager.get_board(guild_id)

    for category in guild.categories:
        if config.is_player_category(category.name):
            player_category = category
            break

    if not player_category:
        # FIXME this shouldn't be an Error/this should propagate
        raise RuntimeError("No player category found")

    name_to_player: dict[str, Player] = {}
    for player in board.players:
        name_to_player[player.name.lower()] = player

    tasks = []

    for channel in player_category.channels:
        player = get_player_by_channel(channel, manager, guild.id)

        if not player or (filter_player and player != filter_player):
            continue

        message = f"Here is the {name} for {board.get_year_str()} {board.phase.name}"
        # capture local of player
        tasks.append(
            map_publish_task(
                lambda player=player: map_caller(manager, guild_id, player),
                channel,
                message,
            )
        )

    await asyncio.gather(*tasks)


# if possible save one svg slot for others
fow_export_limit = asyncio.Semaphore(
    max(int(os.getenv("simultaneous_svg_exports_limit")) - 1, 1)
)


async def map_publish_task(map_maker, channel, message):
    async with fow_export_limit:
        file, file_name = map_maker()
        file, file_name = await svg_to_png(file, file_name)
        await send_message_and_file(
            channel=channel,
            message=message,
            file=file,
            file_name=file_name,
            file_in_embed=False,
        )



async def publish_fow_order_logs(ctx: commands.Context, manager: Manager):
    player_category = None

    guild = ctx.guild
    guild_id = guild.id
    board = manager.get_board(guild_id)

    if not board.fow:
        raise ValueError("This is not a fog of war game")

    filter_player = board.get_player(
        ctx.message.content.removeprefix(ctx.prefix + ctx.invoked_with).strip()
    )

    for category in guild.categories:
        if config.is_player_category(category.name):
            player_category = category
            break

    if not player_category:
        return "No player category found"

    name_to_player: dict[str, Player] = {}
    for player in board.players:
        name_to_player[player.name.lower()] = player

    for channel in player_category.channels:
        player = get_player_by_channel(channel, manager, guild.id)

        if not player or (filter_player and player != filter_player):
            continue

        message = get_filtered_orders(board, player)

        await send_message_and_file(channel=channel, message=message)

    return "Successful"


async def ping_players(ctx: commands.Context, manager: Manager) -> None:

    player_categories: list[CategoryChannel] = []

    timestamp = re.match(
        r"<t:(\d+):[a-zA-Z]>",
        ctx.message.content.removeprefix(ctx.prefix + ctx.invoked_with).strip(),
    )
    if timestamp:
        timestamp = f"<t:{timestamp.group(1)}:R>"

    guild = ctx.guild
    guild_id = guild.id
    board = manager.get_board(guild_id)

    for category in guild.categories:
        # TODO hacky
        if config.is_player_category(category.name) or (
            board.is_chaos() and "Order" in category.name
        ):
            player_categories.append(category)

    if len(player_categories) == 0:
        log_command(logger, ctx, message=f"No player category found")
        await send_message_and_file(
            channel=ctx.channel,
            message="No player category found",
            embed_colour=ERROR_COLOUR,
        )
        return

    # find player roles
    if not board.is_chaos():
        name_to_player: dict[str, Player] = dict()
        player_to_role: dict[Player | None, Role] = dict()
        for player in board.players:
            name_to_player[player.name.lower()] = player

        player_roles: set[Role] = set()

        for role in guild.roles:
            if config.is_player_role(role.name):
                player_roles.add(role)

            player = name_to_player.get(role.name.lower())
            if player:
                player_to_role[player] = role

        if len(player_roles) == 0:
            log_command(logger, ctx, message=f"No player role found")
            await send_message_and_file(
                channel=ctx.channel,
                message="No player role found",
                embed_colour=ERROR_COLOUR,
            )
            return

    response = None
    pinged_players = 0
    failed_players = []

    for player_category in player_categories:
        for channel in player_category.channels:
            player = get_player_by_channel(
                channel, manager, guild.id, ignore_catagory=board.is_chaos()
            )

            if not player:
                await send_message_and_file(
                    channel=ctx.channel, title=f"Couldn't find player for {channel}"
                )
                continue

            if not board.is_chaos():
                role = player_to_role.get(player)
                if not role:
                    log_command(
                        logger,
                        ctx,
                        message=f"Missing player role for player {player.name} in guild {guild_id}",
                        level=logging.WARN,
                    )
                    continue

                # Find users which have a player role to not ping spectators
                users = set(
                    filter(lambda m: len(set(m.roles) & player_roles) > 0, role.members)
                )
            else:
                users = set()
                # Find users with access to this channel
                for overwritter, permission in channel.overwrites.items():
                    if isinstance(overwritter, Member):
                        if permission.view_channel:
                            users.add(overwritter)
                        pass

            if len(users) == 0:
                failed_players.append(player)
                continue

            if phase.is_builds(board.phase):
                count = len(player.centers) - len(player.units)

                current = 0
                has_disbands = False
                has_builds = False
                for order in player.build_orders:
                    if isinstance(order, Disband):
                        current -= 1
                        has_disbands = True
                    elif isinstance(order, Build):
                        current += 1
                        has_builds = True

                difference = abs(current - count)
                if difference != 1:
                    order_text = "orders"
                else:
                    order_text = "order"

                if has_builds and has_disbands:
                    response = f"Hey {''.join([u.mention for u in users])}, you have both build and disband orders. Please get this looked at."
                elif count >= 0:
                    available_centers = [
                        center
                        for center in player.centers
                        if center.unit is None
                        and (
                            center.core == player
                            or "build anywhere" in board.data.get("adju flags", [])
                        )
                    ]
                    available = min(len(available_centers), count)

                    difference = abs(current - available)
                    if current > available:
                        response = f"Hey {''.join([u.mention for u in users])}, you have {difference} more build {order_text} than possible. Please get this looked at."
                    elif current < available:
                        response = f"Hey {''.join([u.mention for u in users])}, you have {difference} less build {order_text} than necessary. Make sure that you want to waive."
                elif count < 0:
                    if current < count:
                        response = f"Hey {''.join([u.mention for u in users])}, you have {difference} more disband {order_text} than necessary. Please get this looked at."
                    elif current > count:
                        response = f"Hey {''.join([u.mention for u in users])}, you have {difference} less disband {order_text} than required. Please get this looked at."
            else:
                if phase.is_retreats(board.phase):
                    in_moves = lambda u: u == u.province.dislodged_unit
                else:
                    in_moves = lambda _: True

                missing = [
                    unit
                    for unit in player.units
                    if unit.order is None and in_moves(unit)
                ]
                if len(missing) != 1:
                    unit_text = "units"
                else:
                    unit_text = "unit"

                if missing:
                    response = f"Hey **{''.join([u.mention for u in users])}**, you are missing moves for the following {len(missing)} {unit_text}:"
                    for unit in sorted(missing, key=lambda _unit: _unit.province.name):
                        response += f"\n{unit}"

            if response:
                pinged_players += 1
                if timestamp:
                    response += f"\n The orders deadline is {timestamp}."
                await channel.send(response)
                response = None

    log_command(logger, ctx, message=f"Pinged {pinged_players} players")
    await send_message_and_file(
        channel=ctx.channel, title=f"Pinged {pinged_players} players"
    )

    if len(failed_players) > 0:
        await send_message_and_file(
            channel=ctx.channel,
            title=f"Failed to find the following players: {','.join([player.name for player in failed_players])}",
        )


async def archive(ctx: commands.Context, _: Manager) -> None:
    categories = [channel.category for channel in ctx.message.channel_mentions]
    if not categories:
        await send_message_and_file(
            channel=ctx.channel,
            message="This channel is not part of a category.",
            embed_colour=ERROR_COLOUR,
        )
        return

    for category in categories:
        for channel in category.channels:
            overwrites = channel.overwrites

            # Remove all permissions except for everyone
            overwrites.clear()
            overwrites[ctx.guild.default_role] = PermissionOverwrite(
                read_messages=True, send_messages=False
            )

            # Apply the updated overwrites
            await channel.edit(overwrites=overwrites)

    message = f"The following catagories have been archived: {' '.join([catagory.name for catagory in categories])}"
    log_command(logger, ctx, message=f"Archived {len(categories)} Channels")
    await send_message_and_file(channel=ctx.channel, message=message)


async def blitz(ctx: commands.Context, manager: Manager) -> None:
    board = manager.get_board(ctx.guild.id)
    cs = []
    pla = sorted(board.players, key=lambda p: p.name)
    for p1 in pla:
        for p2 in pla:
            if p1.name < p2.name:
                c = f"{p1.name}-{p2.name}"
                cs.append((c, p1, p2))

    cos: list[CategoryChannel] = []

    guild = ctx.guild

    for category in guild.categories:
        if category.name.lower().startswith("comms"):
            cos.append(category)

    available = 0
    for cat in cos:
        available += 50 - len(cat.channels)

    # if available < len(cs):
    #     await send_message_and_file(channel=ctx.channel, message="Not enough available comms")
    #     return

    name_to_player: dict[str, Player] = dict()
    player_to_role: dict[Player | None, Role] = dict()
    for player in board.players:
        name_to_player[player.name.lower()] = player

    spectator_role = None

    for role in guild.roles:
        if role.name.lower() == "spectator":
            spectator_role = role

        player = name_to_player.get(role.name.lower())
        if player:
            player_to_role[player] = role

    if spectator_role == None:
        await send_message_and_file(
            channel=ctx.channel, message=f"Missing spectator role"
        )
        return

    for player in board.players:
        if not player_to_role.get(player):
            await send_message_and_file(
                channel=ctx.channel, message=f"Missing player role for {player.name}"
            )
            return

    current_cat = cos.pop(0)
    available = 50 - len(current_cat.channels)
    while len(cs) > 0:
        while available == 0:
            current_cat = cos.pop(0)
            available = 50 - len(current_cat.channels)

        assert available > 0

        name, p1, p2 = cs.pop(0)

        overwrites = {
            guild.default_role: PermissionOverwrite(view_channel=False),
            spectator_role: PermissionOverwrite(view_channel=True),
            player_to_role[p1]: PermissionOverwrite(view_channel=True),
            player_to_role[p2]: PermissionOverwrite(view_channel=True),
        }

        await current_cat.create_text_channel(name, overwrites=overwrites)

        available -= 1


async def wipe(ctx: commands.Context, manager: Manager) -> None:
    board = manager.get_board(ctx.guild.id)
    cs = []
    pla = sorted(board.players, key=lambda p: p.name)
    for p1 in pla:
        for p2 in pla:
            if p1.name < p2.name:
                c = f"{p1.name}-{p2.name}"
                cs.append(c.lower())

    guild = ctx.guild

    for channel in guild.channels:
        if channel.name in cs:
            await channel.delete()


async def nick(ctx: commands.Context, manager: Manager) -> None:
    name: str = ctx.author.nick
    if name == None:
        name = ctx.author.name
    if "]" in name:
        prefix = name.split("] ", 1)[0]
        prefix = prefix + "] "
    else:
        prefix = ""
    name = ctx.message.content.removeprefix(ctx.prefix + ctx.invoked_with).strip()
    if name == "":
        await send_message_and_file(
            channel=ctx.channel,
            embed_colour=ERROR_COLOUR,
            message=f"A nickname must be at least 1 character",
        )
        return
    if len(prefix + name) > 32:
        await send_message_and_file(
            channel=ctx.channel,
            embed_colour=ERROR_COLOUR,
            message=f"A nickname must be at less than 32 total characters.\n Yours is {len(prefix + name)}",
        )
        return
    await ctx.author.edit(nick=prefix + name)
    await send_message_and_file(
        channel=ctx.channel, message=f"Nickname updated to `{prefix + name}`"
    )

async def record_spec(ctx: commands.Context, manager: Manager) -> None:
    guild = ctx.guild 
    if not guild:
        return

    if len(ctx.message.role_mentions) == 0:
        await send_message_and_file(channel=ctx.channel, title="Error", message="Did not mention a nation.", embed_colour=ERROR_COLOUR)
        return

    if len(ctx.message.mentions) == 0:
        await send_message_and_file(channel=ctx.channel, title="Error", message="Did not mention a user.", embed_colour=ERROR_COLOUR)
        return

    user = ctx.message.mentions[0]
    user_id = user.id

    power_role = ctx.message.role_mentions[0]
    power_id = power_role.id

    out = manager.save_spec_request(guild.id, user_id, power_id)
    await send_message_and_file(
        channel=ctx.channel, message=out
    )

async def backlog_specs(ctx: commands.Context, manager: Manager) -> None:
    guild = ctx.guild
    if not guild:
        return

    cspec = discord_find(lambda r: r.name == "Country Spectator", guild.roles)
    if cspec is None:
        await send_message_and_file(channel=ctx.channel, title="Error", message="There is no Country Spectator role in this server.")
        return

    out = ""
    for member in guild.members:
        if cspec not in member.roles:
            continue
        
        power_role = None
        for role in member.roles:
            if discord_find(lambda c: c.name == f"{role.name.lower()}-orders", guild.text_channels):
                power_role = role
                break

        if power_role is None:
            continue

        result = manager.save_spec_request(guild.id, member.id, power_role.id)
        out += f"{member.mention} -> {power_role.mention}: {result}\n"

    await send_message_and_file(channel=ctx.channel, title="Spectator Backlog Results", message=out)

class ContainedPrinter:
    def __init__(self):
        self.text = ""
    def __call__(self, *args):
        self.text += ' '.join(map(str, args)) + '\n'


async def exec_py(ctx: commands.Context, manager: Manager) -> None:
    board = manager.get_board(ctx.guild.id)
    code = (
        ctx.message.content.removeprefix(ctx.prefix + ctx.invoked_with)
        .strip()
        .strip("`")
    )

    embed_print = ContainedPrinter()

    try:
        exec(code, {"print": embed_print, "board": board})
    except Exception as e:
        embed_print("\n" + repr(e))

    if embed_print.text:
        await send_message_and_file(channel=ctx.channel, message=embed_print.text)
    manager._database.delete_board(board)

    manager._database.save_board(ctx.guild.id, board)

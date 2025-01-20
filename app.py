from flask import Flask, render_template, request, redirect
from matplotlib import pyplot as plt
import sqlite3
import csv
import chess.pgn
import os
from datetime import datetime
app=Flask(__name__,template_folder='templates',static_folder='static')

def db():
    conn = sqlite3.connect("data/main.db")
    c = conn.cursor()
    c.execute('''
    CREATE TABLE IF NOT EXISTS players (
        name TEXT NOT NULL,
        rating INTEGER NOT NULL,
        ccr REAL NOT NULL,
        tourns INTEGER NOT NULL,
        podiums INTEGER NOT NULL
    )
    ''')
    conn.commit()

    c.execute('''
    CREATE TABLE IF NOT EXISTS tourns (
        name TEXT NOT NULL,
        winner TEXT NOT NULL,
        date DATE NOT NULL,
        players INTEGER NOT NULL,
        weight INTEGER NOT NULL,
        gif TEXT,
        link TEXT
    )
    ''')
    conn.commit()
    conn.close()
    conn_badges = sqlite3.connect("data/badges.db")
    c_badges = conn_badges.cursor()
    c_badges.execute('''
    CREATE TABLE IF NOT EXISTS dynamic (
        name TEXT NOT NULL UNIQUE,
        holder TEXT NOT NULL,
        url TEXT
    )
    ''')
    conn_badges.commit()
    conn_badges.close()

def ccr(w,r,p,pct,perf,games):
    try:
        ccr = p * 0.12 + 0.0000035 * perf**2 - 0.03 * pct + 0.08 * r
        if games <= 5:
            game_bonus = 0.4 * games
        elif games <= 10:
            game_bonus = 1.75 + 0.15 * (games - 5)
        else:
            game_bonus = 2.8
        ccr += game_bonus
        ccr *= w / 5
    except:
        ccr = 0.0
    return round(ccr, 3)



def ccrdecay(ccr, weight, tournament_date):
    try:
        today = datetime.now()
        days_elapsed = (today - tournament_date).days
        early_decay_days = min(days_elapsed, int(weight * 15))
        early_decay = early_decay_days * 0.005
        late_decay_days = max(0, days_elapsed - int(weight * 15))
        late_decay = late_decay_days * 0.1
        total_decay = early_decay + late_decay
        decayed_ccr = max(0, ccr - total_decay)  
        return decayed_ccr
    except Exception as e:
        print(f"Error calculating CCR decay: {e}")
        return round(ccr,3)


def parse_csv(file):
    try:
        csv_file = file.stream.read().decode('utf-8').splitlines()
        csv_reader = csv.DictReader(csv_file)
        rows = [row for row in csv_reader]
        return rows
    except FileNotFoundError:
        print('File not found')
        return []
    except Exception as e:
        print(f"An error occurred: {e}")
        return []
    
def updateplayer(rows, pgn,w,p):
    try:
        player_stats = {player['Username']: {'games': 0, 'wins': 0} for player in rows}
        pgn_content = pgn.stream.read().decode('utf-8').splitlines()
        from io import StringIO
        pgn_file = StringIO("\n".join(pgn_content))
        while True:
            game = chess.pgn.read_game(pgn_file)
            if game is None:
                break
            white_player = game.headers.get("White", None)
            black_player = game.headers.get("Black", None)
            result = game.headers.get("Result", None)
            if white_player in player_stats:
                player_stats[white_player]['games'] += 1
                if result == "1-0":
                    player_stats[white_player]['wins'] += 1
            if black_player in player_stats:
                player_stats[black_player]['games'] += 1
                if result == "0-1":
                    player_stats[black_player]['wins'] += 1
        for player in rows:
            username = player['Username']
            games = player_stats[username]['games']
            wins = player_stats[username]['wins']
            player['games'] = games
            player['winrate'] = round((wins / games) * 100, 2) if games > 0 else 0
            if games==0: 
                player['ccr']=0.0
                player['pct']=(p-int(player['Rank']))*100/p
                player['Performance']=0
            else:
                pct=round((p-int(player['Rank']))*100/p,2)
                player['pct']=pct
                try:
                    player['ccr']=ccr(w,player['winrate'],int(player['Score']),pct,int(player['Performance']),games)
                except Exception as e:
                    player['ccr']=0.0
                    return redirect('/')
    except Exception as e:
        print('Relay Error from PGN parsing:', e,pct,type(pct))
    return rows

def updateccr():
    try:
        players_conn = sqlite3.connect('data/players.db')
        main_conn = sqlite3.connect('data/main.db')
        players_cursor = players_conn.cursor()
        main_cursor = main_conn.cursor()
        main_cursor.execute('SELECT name FROM players')
        all_players = main_cursor.fetchall()
        for player in all_players:
            username = player[0]
            players_cursor.execute(f'SELECT ccr, date, weight FROM "{username}"')
            tournaments = players_cursor.fetchall()
            total_ccr = 0.0
            for tournament in tournaments:
                raw_ccr, tournament_date, weight = tournament
                tournament_date = datetime.strptime(tournament_date, '%Y-%m-%d')
                decayed_ccr = ccrdecay(raw_ccr, weight, tournament_date)
                total_ccr += decayed_ccr
            main_cursor.execute('''
                UPDATE players
                SET ccr = ?
                WHERE name = ?
            ''', (round(total_ccr, 3), username))
        main_conn.commit()
        players_conn.close()
        main_conn.close()
    except Exception as e:
        print(f"An error occurred while updating CCR with decay: {e}")

def updatedb(rows, tournament_date, tournament_name, weight,winner,players,gif):
    try:
        players_conn = sqlite3.connect('data/players.db')
        players_cursor = players_conn.cursor()
        for row in rows:
            try:
                username = row['Username']
                rating = row['Rating']
                raw_ccr = row['ccr']
                games = row['games']
                winrate = row['winrate']
                rank=row['Rank']
                perf=row['Performance']
            except Exception as f: print('Error in something: ',f)
            podium = 1 if row['pct'] >= 85 else 0
            players_cursor.execute(f'''
                CREATE TABLE IF NOT EXISTS "{username}" (
                    rating INTEGER,
                    ccr REAL,
                    tourn TEXT,
                    games INTEGER,
                    winrate REAL,
                    date DATE,
                    podium INTEGER,
                    weight INTEGER,
                    rank INTEGER,
                    perf INTEGER
                )
            ''')

            players_cursor.execute(f'''
                INSERT INTO "{username}" (rating, ccr, tourn, games, winrate, date, podium, weight,rank,perf)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?,?,?)
            ''', (rating, raw_ccr, tournament_name, games, winrate, tournament_date, podium, weight,rank,perf))

        players_conn.commit()
        players_conn.close()
        main_conn = sqlite3.connect('data/main.db')
        main_cursor = main_conn.cursor()

        for row in rows:
            username = row['Username']
            rating = row['Rating']

            players_conn = sqlite3.connect('data/players.db')
            players_cursor = players_conn.cursor()

            players_cursor.execute(f'SELECT ccr, date, weight FROM "{username}"')
            all_entries = players_cursor.fetchall()

            total_ccr = 0
            for entry_ccr, entry_date, entry_weight in all_entries:
                entry_date_obj = datetime.strptime(entry_date, '%Y-%m-%d')
                total_ccr += ccrdecay(entry_ccr, entry_weight, entry_date_obj)

            players_cursor.execute(f'SELECT COUNT(*) FROM "{username}"')
            tourns = players_cursor.fetchone()[0]

            players_cursor.execute(f'SELECT SUM(podium) FROM "{username}"')
            total_podiums = players_cursor.fetchone()[0]

            players_conn.close()

            main_cursor.execute('SELECT * FROM players WHERE name = ?', (username,))
            result = main_cursor.fetchone()

            if result:
                main_cursor.execute('''
                    UPDATE players
                    SET rating = ?, ccr = ?, tourns = ?, podiums = ?
                    WHERE name = ?
                ''', (rating, total_ccr, tourns, total_podiums, username))
            else:
                main_cursor.execute('''
                    INSERT INTO players (name, rating, ccr, tourns, podiums)
                    VALUES (?, ?, ?, ?, ?)
                ''', (username, rating, total_ccr, tourns, total_podiums))

        main_conn.commit()
        gamelink='https://lichess.org'+gif[30:]
        main_cursor.execute('INSERT INTO tourns (name,winner,date,players,weight,gif,link) VALUES (?,?,?,?,?,?,?)',(tournament_name,winner,tournament_date,players,weight,gif,gamelink))
        main_conn.commit()
        main_conn.close()

        print("Database updated successfully.")

    except Exception as e:
        print(f"An error occurred: {e}")

def update_dynamic_badges():
    try:
        conn = sqlite3.connect("data/main.db")
        c = conn.cursor()
        c.execute('SELECT name, ccr FROM players ORDER BY ccr DESC LIMIT 1')
        highest_ccr = c.fetchone()
        c.execute('SELECT name, rating FROM players WHERE ccr > 0 ORDER BY rating DESC LIMIT 1')
        highest_rated = c.fetchone()
        c.execute('SELECT winner FROM tourns ORDER BY date DESC LIMIT 1')
        current_champion = c.fetchone()
        conn.close()
        conn_badges = sqlite3.connect("data/badges.db")
        c_badges = conn_badges.cursor()
        badges = [
            ("Highest CCR Holder", highest_ccr[0] if highest_ccr else "N/A", "ccr.png"),
            ("Highest Rated Player", highest_rated[0] if highest_rated else "N/A", "rating.png"),
            ("Current Champion", current_champion[0] if current_champion else "N/A", "champion.png")
        ]

        for badge in badges:
            c_badges.execute('''
            INSERT INTO dynamic (name, holder, url)
            VALUES (?, ?, ?)
            ON CONFLICT(name) DO UPDATE SET holder = excluded.holder, url = excluded.url
            ''', badge)
        conn_badges.commit()
        conn_badges.close()

        print("Dynamic badges updated successfully.")
    except Exception as e:
        print(f"Error updating dynamic badges: {e}")




@app.route('/',methods=['GET','POST'])
def index():
    if request.method=='GET':
        return render_template('index.html')
    elif request.method=='POST':
        button=request.form['button']
        if button=='addtourn': return redirect('/verify')
        elif button=='viewplayers':return redirect('/viewplayers')
        elif button=='tutorial': return redirect('/guide')
        elif button=='iconic': return redirect('/iconic')
        elif button=='record': return redirect('/record')

@app.route('/verify', methods=['GET','POST'])
def verify():
    if request.method=='GET': return render_template('pwd.html')
    elif request.method=='POST': 
        if request.form['password']=='motdepasse': return redirect('/add')
        else: return render_template('pwd.html',error=True)


@app.route('/add',methods=['GET','POST','PUT'])
def add():
    if request.method=='GET':
        return render_template('add.html')
    elif request.method=='POST':
        csvfile=request.files['csvfile']
        rows=parse_csv(csvfile)
        w=int(request.form['weight'])
        n=int(request.form['players'])
        winner=request.form['winner']
        pgniconic=request.form['pgniconic']
        date = datetime.strptime(request.form['date'], '%Y-%m-%d').date()
        for row in rows:
            row.setdefault('games',0)
            row.setdefault('winrate',0)
            row.setdefault('ccr',0.0)
        pgnfile=request.files['pgnfile']
        try:
            updateplayer(rows,pgnfile,w,n)
        except Exception as e: print(e)
        updatedb(rows,date,request.form['name'],w,winner,n,pgniconic)
        update_dynamic_badges()
        return render_template('add.html',status=1)



@app.route('/viewplayers', methods=['GET', 'POST'])
def viewplayers():
    try:
        updateccr()
        if request.method == 'GET':
            sort_by = 'ccr'
            conn = sqlite3.connect('data/main.db')
            c = conn.cursor()
            c.execute(f'SELECT * FROM players ORDER BY ccr DESC')
            rows = c.fetchall()
            return render_template('viewplayers.html',data=rows,sort_by=sort_by)
        else:
            sort_by = request.form.get('sort_by', 'ccr')
            sort_column = {
                'ccr': 'ccr DESC',
                'rating': 'rating DESC',
                'podiums': 'podiums DESC, ccr DESC'
            }.get(sort_by, 'ccr DESC')
            conn = sqlite3.connect('data/main.db')
            c = conn.cursor()
            c.execute(f'SELECT * FROM players ORDER BY {sort_column}')
            rows = c.fetchall()
            conn.close()
            return render_template('viewplayers.html', data=rows, sort_by=sort_by)
    except Exception as e:
        print('Relay Error from ViewPlayers: ', e)
        return render_template('viewplayers.html', data=(), sort_by='ccr')



@app.route('/guide')
def guide():
    return render_template('ccr.html')


@app.route('/iconic')
def iconic():
    conn = sqlite3.connect('data/main.db')
    c = conn.cursor()
    c.execute('SELECT * FROM tourns')
    tournaments = c.fetchall()
    conn.close()
    return render_template('iconic.html', tournaments=tournaments)

@app.route('/record',methods=['GET','POST'])
def record():
    if request.method=='GET':
        conn=sqlite3.connect('data/main.db')
        c=conn.cursor()
        c.execute('SELECT name FROM players ORDER BY ccr DESC')
        names=c.fetchall()
        conn.close()
        return render_template('record.html',players=names)
    elif request.method=='POST':
        player=request.form['player_name']
        return redirect('/playerinfo/'+str(player))
    

@app.route('/playerinfo/<player>')
def player_details(player):
    updateccr()
    conn = sqlite3.connect('data/players.db')
    c = conn.cursor()

    c.execute(f'SELECT date, rating, ccr, tourn, games, winrate, podium, weight, rank, perf FROM "{player}" ORDER BY date')
    data = c.fetchall()
    conn.close()

    dates, ratings, performances, ccrs, tournaments = [], [], [], [], []
    total_games, total_podiums = 0, 0
    ccrlive = 0

    try:
        for row in data:
            dates.append(row[0])
            ratings.append(row[1])
            performances.append(row[9])
            ccrs.append(row[2])
            tournaments.append({
                'tourn': row[3],
                'date': row[0],
                'weight': row[7],
                'rank': row[8],
                'rating': row[1],
                'ccr': row[2],
                'performance': row[9],
                'winrate': row[5],
                'games': row[4],
                'wins': round(row[5] * row[4] / 100)
            })
            total_games += row[4]
            total_podiums += row[6]
    except Exception as e:
        print('Error in gathering data:', e)

    conn = sqlite3.connect('data/main.db')
    c = conn.cursor()

    rank = None
    try:
        c.execute('SELECT name, ccr FROM players ORDER BY ccr DESC')
        players_ranked = c.fetchall()
        for index, (name, ccr) in enumerate(players_ranked, start=1):
            if name == player:
                ccrlive = ccr
                rank = index
                break
    except Exception as e:
        print('Error in CCRLIVE or rank:', e, player)
    conn.close()

    conn_badges = sqlite3.connect('data/badges.db')
    c_badges = conn_badges.cursor()
    c_badges.execute('SELECT name, holder, url FROM dynamic WHERE holder = ?', (player,))
    dynamic_badges = [{'name': row[0], 'tooltip': f"Player with {row[0]}!", 'url': row[2]} for row in c_badges.fetchall()]
    conn_badges.close()

    plt.figure(figsize=(12, 8))
    plt.subplot(3, 1, 1)
    plt.plot(dates, ratings, marker='o', label='Rating')
    plt.title('Rating Over Time')
    plt.grid()

    plt.subplot(3, 1, 2)
    plt.plot(dates, performances, marker='o', label='Performance', color='green')
    plt.title('Performance Over Time')
    plt.grid()

    plt.subplot(3, 1, 3)
    plt.plot(dates, ccrs, marker='o', label='Raw CCR', color='red')
    plt.title('Raw CCR Over Time')
    plt.grid()

    plt.tight_layout()
    plt.savefig('static/growth_chart.png')
    plt.close()

    return render_template(
        'details.html',
        player=player,
        tourns=len(data),
        ccr=ccrlive,
        rank=rank,
        rating=ratings[-1] if ratings else 0,
        podiums=total_podiums,
        games=total_games,
        tournaments=tournaments,
        dynamic_badges=dynamic_badges,
    )





if __name__=='__main__':
    if not os.path.exists('data'):
        os.makedirs('data')
    db()
    app.run(host='0.0.0.0',port=5555,debug=True)
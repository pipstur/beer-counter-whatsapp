# beer-counter-whatsapp
Python implementation of a automated beer counter and dashboard for a personal whatsapp group. Automated message grabbing hosted locally, database hosted on Supabase, dashboard hosted on Streamlit.


# Setup
0. Prerequisites:
    - Python 3.10
    - Git
    - uv
    - Whatsapp Web account (though use at own risk, since it is technically against Whatsapp's TOS)
1. Clone the repository:
   ```bash
   git clone https://github.com/pipstur/beer-counter-whatsapp.git
   ```
2. Setup environment:
    ```bash
    cd beer-counter-whatsapp
    uv venv venv
    source venv/bin/activate  # On Windows use `venv\Scripts\activate`
    uv pip install -r requirements.txt
    ```
3. Setup Supabase:
    - Create a free account on [Supabase](https://supabase.com/)
    - Create a new project
    - Go to the SQL editor and run the SQL commands to create the necessary tables.
    ```sql
        create table messages (
            id text primary key,
            user_name text not null,
            timestamp timestamptz not null,
            beer_count int not null
        );
    ```     
    - Get your API URL and anon key from the project settings.
4. Setup environment variables:
    - Create a `.env` file in the root directory with the following content:
      ```
      SUPABASE_URL=your_supabase_url
      SUPABASE_ANON_KEY=your_supabase_anon_key
      ```
5. Run the message grabber:
    ```bash
    python main.py
    ```
6. Open the dashboard:
    - Either on the [link](https://beer-counter-whatsapp.streamlit.app/).
    - Or run locally with:
      ```bash
      streamlit run streamlit/app.py
      ```

# Streamlit dashboard screenshots
![Streamlit dashboard](https://i.imgur.com/Ir8pfCH.png)

## Leaderboard and most drunk at times
![Leaderboard and most drunk at times](https://i.imgur.com/OUWdpg2.png)

## User timelines
![User timelines](https://i.imgur.com/qD0GXnJ.png)

## Filters
![Filter by date, aggregation level (day/week/month) and users](https://i.imgur.com/93WkiQy.png)


from .ui.app import main

# The guard matters: the bot thinks in a spawned process, which re-imports this module.
if __name__ == "__main__":
    main()

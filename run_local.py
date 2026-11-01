from waitress import serve
from portal import create_app

if __name__ == '__main__':
    app = create_app()
    from portal.migrations import migrate_schema
    with app.app_context():
        migrate_schema()
    print('Portal lokal: http://127.0.0.1:6502', flush=True)
    print('Mode akses: ' + ('login' if app.config['AUTH_REQUIRED'] else 'langsung tanpa login'), flush=True)
    serve(app, host='127.0.0.1', port=6502, threads=4)

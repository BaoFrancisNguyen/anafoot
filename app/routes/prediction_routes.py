# app/routes/prediction_routes.py
from flask import Blueprint, render_template, request, jsonify
from app.services.ai_predictor import predict_match_result

prediction_bp = Blueprint('predict', __name__)

@prediction_bp.route('/', methods=['GET', 'POST'])
def predict_match():
    """Interface de prédiction de match"""
    if request.method == 'POST':
        home_team = request.form.get('home_team')
        away_team = request.form.get('away_team')
        match_date = request.form.get('match_date')
        
        prediction = predict_match_result(home_team, away_team, match_date)
        return render_template('predictions.html', prediction=prediction)
    
    return render_template('predictions.html')